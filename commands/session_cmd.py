import storage.sessions as sess_store
import storage.projects as proj_store
import layers.codex_exec as claude_exec
from utils.discord_helpers import followup, opts


async def handle(sub: str, sub_opts: list, token: str, channel_id: str):
    o = opts(sub_opts)

    if sub == "list":
        sessions = sess_store.list_active()
        if not sessions:
            return await followup(token, "No active sessions.")
        lines = ["**Active Sessions:**"]
        for s in sessions:
            backend_id = s.get("backend_session_id", "")
            backend_text = f" — codex: `{backend_id[:12]}`" if backend_id else ""
            lines.append(
                f"• `{s['id']}` — project: **{s['project_name']}** "
                f"— channel: `{s['channel_id']}` — msgs: {s['message_count']}{backend_text}"
            )
        await followup(token, "\n".join(lines))

    elif sub == "resume":
        session_id = o.get("id", "")
        sess = sess_store.get(session_id)
        if not sess:
            return await followup(token, f"❌ Session `{session_id}` not found.")
        # Close any current active session on this channel before resuming
        current = sess_store.get_active_for_channel(channel_id)
        if current and current["id"] != session_id:
            import layers.codex_exec as claude_exec
            claude_exec.close_session_shell(current["id"])
            sess_store.close(current["id"])
        if sess["status"] != "active":
            import storage.base as base
            import storage.sessions as s
            base.upsert(s.TABLE, s.SCHEMA, "id", session_id, {
                "status": "active",
                "channel_id": channel_id,  # re-associate with this channel
            })
        # Re-associate project with channel
        proj = proj_store.get(sess["project_name"]) if sess.get("project_name") else None
        if proj:
            proj_store.set_active_channel(sess["project_name"], channel_id)
        await followup(token,
            f"✅ Session `{session_id}` resumed.\n"
            f"Project: **{sess['project_name']}** — {sess['message_count']} messages\n"
            f"Codex thread: `{sess.get('backend_session_id', '') or 'not started yet'}`\n"
            f"Last prompt: _{sess.get('last_prompt', '(none)')[:100]}_"
        )

    elif sub == "close":
        session_id = o.get("id", "")
        if not session_id:
            # Close channel's active session
            sess = sess_store.get_active_for_channel(channel_id)
            if not sess:
                return await followup(token, "No active session in this channel.")
            session_id = sess["id"]
        sess_store.close(session_id)
        proj_store.clear_active_channel(channel_id)
        await followup(token,
            f"✅ Session `{session_id}` closed.\n"
            f"Project detached from this channel. Use `/project use <name>` to start fresh."
        )

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
