"""What a saved query does, read from DuckDB's own parser and not from its text.

json_serialize_sql gives the parsed tree of a statement. json_deserialize_sql turns a changed tree back into
SQL, for example the same FROM and WHERE with count(*) in place of the SELECT list. The query is only ever
a text value passed to these two functions: it does not run here, and this connection has nothing to read.

The tree's field names differ between DuckDB versions (2.0 changed constants and casts), so this module
reads few of them, and every caller treats None as "cannot tell".
"""

import copy
import functools
import json
import threading
from decimal import Decimal, InvalidOperation

from . import engine

MAX_SQL = 100_000  # characters; a longer query is not parsed, so its checks say nothing
_lock = threading.Lock()
_state = {"con": None}


def _call(function, text):
    """json_serialize_sql or json_deserialize_sql on one text value; None when it fails."""
    try:
        with _lock:
            if _state["con"] is None:
                con = engine._duckdb().connect(":memory:", config={"autoinstall_known_extensions": False,
                                                                 "autoload_known_extensions": False})
                con.execute("SET enable_external_access = false")
                con.execute("SET lock_configuration = true")
                _state["con"] = con
            return _state["con"].execute(f"SELECT {function}(?)", [text]).fetchone()[0]
    except Exception:
        return None


@functools.lru_cache(maxsize=256)
def _tree(sql):
    """The parsed tree of one statement, or None. Read-only: the same object is given to every caller."""
    if len(sql) > MAX_SQL:
        return None  # ponytail: 256 cached trees of unbounded size would hold a lot of memory
    try:
        tree = json.loads(_call("json_serialize_sql", sql) or "{}")
        tree["statements"][0]["node"]["type"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return None if tree.get("error") or len(tree["statements"]) != 1 else tree


def parse(sql):
    """The Query for one plain SELECT statement; None for anything else (no parse, UNION, several statements)."""
    tree = _tree(sql)
    return Query(tree) if tree and tree["statements"][0]["node"]["type"] == "SELECT_NODE" else None


def tables(sql):
    """(schema or "", table) of every table a statement names, also in subqueries and UNION parts; None when
    DuckDB cannot parse it."""
    tree = _tree(sql)
    if tree is None:
        return None
    return {(d.get("schema_name") or "", d.get("table_name")) for d in _dicts(tree) if d.get("type") == "BASE_TABLE"}


def _dicts(x, subqueries=True):
    """Every dict under a part of the tree. subqueries=False stays out of nested SELECTs."""
    if isinstance(x, dict):
        yield x
        for key, value in x.items():
            if subqueries or key not in ("subquery", "cte_map"):
                yield from _dicts(value, subqueries)
    elif isinstance(x, list):
        for value in x:
            yield from _dicts(value, subqueries)


def calls(x, subqueries=True):
    """(lower-case name, node) of every function call under x. Operators such as / and * are calls too."""
    for d in _dicts(x, subqueries):
        if d.get("function_name"):
            yield d["function_name"].lower(), d


def args(call):
    """The argument expressions of a function call (DuckDB 1.x: children; 2.x: arguments)."""
    return call.get("children") or [a.get("expression") for a in call.get("arguments") or []]


def column(e):
    """The column name of a plain column reference (o.amount gives amount), else None."""
    return e["column_names"][-1] if isinstance(e, dict) and e.get("class") == "COLUMN_REF" else None


def constant(e):
    """The value of a constant as str, int, Decimal or bool; None for NULL and for anything that is not a constant."""
    if not isinstance(e, dict) or e.get("class") != "CONSTANT":
        return None
    try:
        if "literal" in e:  # DuckDB 2.x: the text as written
            kind, text = e["literal"].get("kind"), e["literal"].get("text")
            return {"STRING": str, "INTEGER": int, "NUMERIC": Decimal, "BOOLEAN": lambda t: t == "true"}[kind](text)
        value = e["value"]  # DuckDB 1.x: a typed value; a DECIMAL is a whole number and a scale
        if value.get("is_null"):
            return None
        if value["type"]["id"] == "DECIMAL":
            return Decimal(value["value"]).scaleb(-value["type"]["type_info"]["scale"])
        return Decimal(repr(value["value"])) if isinstance(value["value"], float) else value["value"]
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None


def cast_to(e):
    """The type a CAST gives, in upper case (CAST(ts AS DATE) and ts::DATE give DATE), else None."""
    if not isinstance(e, dict) or e.get("class") != "CAST":
        return None
    target = (e.get("cast_type") or {}).get("id") or (e.get("type_expr") or {}).get("type_name")
    return str(target).upper() if target else None


def _ref(table):
    """SQL for a table reference of the tree: "shop"."orders" or "sales"."""
    parts = [table.get("schema_name"), table.get("table_name")]
    return ".".join(engine.ident(p) for p in parts if p)


class Query:
    """One parsed SELECT."""

    def __init__(self, tree):
        self.tree = tree
        self.node = tree["statements"][0]["node"]
        self.select = self.node.get("select_list") or []
        self.where = self.node.get("where_clause")
        self.ctes = [c.get("key") for c in (self.node.get("cte_map") or {}).get("map") or []]

    def _modifier(self, kind):
        return next((m for m in self.node.get("modifiers") or [] if m.get("type") == kind), None)

    @property
    def order(self):
        """[(expression, descending)] of ORDER BY."""
        m = self._modifier("ORDER_MODIFIER")
        return [(o.get("expression"), o.get("type") == "DESCENDING") for o in (m or {}).get("orders") or []]

    @property
    def limit(self):
        """The row count of LIMIT when it is a whole number, else None."""
        n = constant((self._modifier("LIMIT_MODIFIER") or {}).get("limit"))
        return n if isinstance(n, int) and not isinstance(n, bool) else None

    def source(self):
        """What the outer FROM reads:
        ("table", SQL reference, name) for one table or view;
        ("join", left reference, left name, right reference, right name, left key, right key) for two tables joined
        on one column each; ("helper", name) for a WITH result or a subquery; ("other",) for the rest."""
        f = self.node.get("from_table") or {}
        if f.get("type") == "BASE_TABLE":
            name = f.get("table_name")
            return ("helper", name) if name in self.ctes and not f.get("schema_name") else ("table", _ref(f), name)
        if f.get("type") == "SUBQUERY":
            return ("helper", f.get("alias") or "a subquery")
        if f.get("type") == "JOIN":
            left, right = f.get("left") or {}, f.get("right") or {}
            if left.get("type") != "BASE_TABLE" or right.get("type") != "BASE_TABLE" or {left.get("table_name"), right.get("table_name")} & set(self.ctes):
                return ("other",)
            keys = self._join_keys(f, left)
            if keys:
                return ("join", _ref(left), left.get("table_name"), _ref(right), right.get("table_name"), *keys)
        return ("other",)

    @staticmethod
    def _join_keys(join, left):
        """(left column, right column) of USING (k) or ON a.k = b.k, else None."""
        using = join.get("using_columns") or []
        if len(using) == 1:
            return using[0], using[0]
        cond = join.get("condition") or {}
        a, b = cond.get("left"), cond.get("right")
        if cond.get("type") != "COMPARE_EQUAL" or not column(a) or not column(b):
            return None
        if len(a["column_names"]) < 2 or len(b["column_names"]) < 2:
            return None  # without a table name on each side we cannot tell whose column it is
        if b["column_names"][-2].lower() in ((left.get("alias") or "").lower(), (left.get("table_name") or "").lower()):
            a, b = b, a
        return column(a), column(b)

    def _changed(self, change):
        """The SQL of this tree after a change to its outer node; None when DuckDB cannot write it."""
        tree = copy.deepcopy(self.tree)
        try:
            change(tree["statements"][0]["node"])
        except (AttributeError, KeyError, TypeError):
            return None
        return _call("json_deserialize_sql", json.dumps(tree))

    def count_sql(self, where=True):
        """SQL that counts the rows the query reads: the same WITH, FROM and joins, with or without its WHERE."""
        def change(node):
            node.update(select_list=copy.deepcopy(_count_star()), modifiers=[], group_expressions=[], group_sets=[],
                        having=None, qualify=None, aggregate_handling="STANDARD_HANDLING")
            if not where:
                node["where_clause"] = None
        return self._changed(change)

    def sql(self, order=True, limit=None):
        """The query as SQL without its LIMIT (limit=None) or with another one, and with or without its ORDER BY."""
        def change(node):
            keep = [m for m in node.get("modifiers") or []
                    if m.get("type") != "LIMIT_MODIFIER" and (order or m.get("type") != "ORDER_MODIFIER")]
            node["modifiers"] = keep + (copy.deepcopy(_limit(limit)) if limit else [])
        return self._changed(change)


def _count_star():
    return parse("SELECT count(*)").select


def _limit(n):
    return [parse(f"SELECT 1 LIMIT {int(n)}")._modifier("LIMIT_MODIFIER")]
