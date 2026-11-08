"""Grimoire: learn and explore data with fewer tokens."""

from . import schemas, tools

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
