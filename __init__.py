"""Grimoire: learn and explore data with fewer tokens."""

from . import guard, schemas, tools

_HANDLERS = {
    "grimoire_attach": tools.attach,
    "grimoire_profile": tools.profile,
    "grimoire_query": tools.query,
    "grimoire_note": tools.note,
    "grimoire_catalog": tools.catalog,
}


def register(ctx):
    """Called once by Hermes at startup."""
    for schema in schemas.ALL:
        ctx.register_tool(
            name=schema["name"],
            toolset="grimoire",
            schema=schema,
            handler=_HANDLERS[schema["name"]],
        )

    # Users can change the size limit, or set 0 to turn the guard off:
    # plugins.entries.grimoire.settings.read_guard_kb in config.yaml
    limit_kb = ctx.get_config("read_guard_kb", default=guard.DEFAULT_LIMIT_KB)

    def before_tool(tool_name, args, **kwargs):
        try:
            cwd = ctx.session_cwd()
        except Exception:
            cwd = None
        return guard.check(tool_name, args, cwd=cwd, limit_kb=limit_kb)

    ctx.register_hook("pre_tool_call", before_tool)
