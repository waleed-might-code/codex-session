import os
import subprocess
import storage.projects as proj_store
import storage.sessions as sess_store
from utils.discord_helpers import followup, followup_chunks, opts, subcommand


async def handle(sub: str, sub_opts: list, token: str, channel_id: str, user_id: str):
    o = opts(sub_opts)

    if sub == "add":
        name = o.get("name", "")
        desc = o.get("description", "")
        if not name:
            return await followup(token, "❌ `name` is required.")
        path = o.get("path", "")
        if not path:
            projects_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "projects")
            path = os.path.join(projects_dir, name)
            os.makedirs(path, exist_ok=True)
        try:
            rec = proj_store.add(name, path, desc)
            # Auto-detect git branch
            try:
                branch = subprocess.check_output("git branch --show-current", shell=True,
                                                  cwd=rec["path"], text=True).strip()
                proj_store.update_branch(name, branch)
            except Exception:
                branch = "unknown"
            await followup(token,
                f"✅ Project **{name}** added.\n"
                f"📁 `{rec['path']}`\n"
                f"🌿 Branch: `{branch}`"
            )
        except ValueError as e:
            await followup(token, f"❌ {e}")

    elif sub == "list":
        projects = proj_store.list_all()
        if not projects:
            return await followup(token, "No projects yet. Use `/project add`.")
        lines = ["**Projects:**"]
        for p in projects:
            branch = f" `{p['git_branch']}`" if p.get("git_branch") else ""
            lines.append(f"• **{p['name']}** — `{p['path']}`{branch}")
        await followup(token, "\n".join(lines))

    elif sub == "use":
        name = o.get("name", "")
        proj = proj_store.get(name)
        if not proj:
            return await followup(token, f"❌ Project `{name}` not found.")
        proj_store.set_active_channel(name, channel_id)
        # Close any active session that belongs to a different project
        sess = sess_store.get_active_for_channel(channel_id)
        if sess and sess.get("project_name") != name:
            import layers.codex_exec as claude_exec
            claude_exec.close_session_shell(sess["id"])
            sess_store.close(sess["id"])
            sess = None
        if not sess or sess.get("project_name") != name:
            sess = sess_store.get_active_root_for_project(name)
            if sess:
                sess_store.attach_channel(sess["id"], channel_id)
            else:
                sess = sess_store.create(name, channel_id, user_id)
        await followup(token,
            f"✅ Active project: **{name}**\n"
            f"📁 `{proj['path']}`\n"
            f"🔑 Session: `{sess['id']}`\n"
            f"💬 Just type in this channel to chat with Codex."
        )

    elif sub == "info":
        proj = proj_store.get_by_channel(channel_id)
        if not proj:
            return await followup(token, "No active project in this channel. Use `/project use`.")
        sess = sess_store.get_active_for_channel(channel_id)
        try:
            git_log = subprocess.check_output(
                "git log --oneline -5 2>/dev/null", shell=True,
                cwd=proj["path"], text=True
            ).strip()
        except Exception:
            git_log = "(not a git repo)"
        await followup(token,
            f"**Project: {proj['name']}**\n"
            f"📁 `{proj['path']}`\n"
            f"🌿 Branch: `{proj.get('git_branch', 'unknown')}`\n"
            f"🔑 Session: `{sess['id'] if sess else 'none'}`\n"
            f"**Recent commits:**\n```\n{git_log}\n```"
        )

    elif sub == "remove":
        name = o.get("name", "")
        proj = proj_store.get(name)
        if not proj:
            return await followup(token, f"❌ Project `{name}` not found.")
        proj_store.remove(name)
        await followup(token, f"✅ Project **{name}** removed.")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
