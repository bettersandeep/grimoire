"""Grimoire: learn and explore data with fewer tokens."""

from pathlib import Path

from . import commands, guard, learning, recipes, schemas, tools

_HANDLERS = {
    "grimoire_attach": tools.attach,
    "grimoire_profile": tools.profile,
    "grimoire_query": tools.query,
    "grimoire_drivers": tools.drivers,
    "grimoire_compare": tools.compare,
    "grimoire_note": tools.note,
    "grimoire_merge": tools.merge,
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

    ctx.register_command("grimoire", commands.run, description="Grimoire status, query SQL, skipped lines and merges",
                         args_hint="[setup | sql q12 | report | learn on | merges]")

    tools.configure(allow_private_folders=ctx.get_config("allow_private_folders", default=False))

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

    def before_turn(user_message=None, session_id=None, **kwargs):
        tools.remember_user_message(session_id, user_message)
        try:
            cwd = ctx.session_cwd()
        except Exception:
            cwd = None
        try:
            hint = tools.auto_attach(user_message, session_id, cwd)
        except Exception:
            hint = guard.data_file_hint(user_message)
        parts = [hint] if hint else []
        if hint or tools.used_grimoire(session_id):
            found = recipes.for_message(user_message)
            if found:  # only when the question calls for one; nothing otherwise
                parts.append("[Grimoire] DuckDB recipe" + ("s" if len(found) > 1 else "") + ": " + " ".join(found))
            try:
                if tools.learning_state()[1]:
                    parts.append(learning.PREDICT_CONTEXT)
            except Exception:
                pass  # a settings problem must not block the turn
        return {"context": "\n".join(parts)} if parts else None

    ctx.register_hook("pre_llm_call", before_turn)

    # Prediction mode: the user's answer to the clarify question is the guess.
    def after_tool(tool_name=None, result=None, session_id=None, **kwargs):
        if tool_name == "clarify" and result:
            tools.record_guess(session_id, result)

    ctx.register_hook("post_tool_call", after_tool)

    # Only two numbers per model call, to show what a chat costs: the tool count before it,
    # and the provider's input token count after it. No message content is kept.
    def before_api(session_id=None, tool_count=None, **kwargs):
        tools.remember_call(session_id, tool_count=tool_count)

    def after_api(session_id=None, usage=None, **kwargs):
        tools.remember_call(session_id, tokens=(usage or {}).get("prompt_tokens"))

    ctx.register_hook("pre_api_request", before_api)
    ctx.register_hook("post_api_request", after_api)

    ctx.register_skill("explore-data", Path(__file__).resolve().parent / "skills" / "explore-data" / "SKILL.md",
                       description="Answer questions about CSV, JSON, Parquet or SQLite files with Grimoire.")

    # Append-only, so the reply keeps streaming; the footer prints after it (no hold_stream).
    def after_reply(response_text=None, session_id=None, **kwargs):
        try:
            note = tools.check_reply(response_text, session_id)
        except Exception:
            return None  # never break a reply because the check failed
        return response_text + note if note else None

    ctx.register_hook("transform_llm_output", after_reply)
