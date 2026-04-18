import storage.projects as proj_store
import storage.sessions as sess_store
import utils.discord_helpers as dh


def get_active_thread_session(project: dict | None) -> dict | None:
    if not project:
        return None

    thread_id = project.get("active_thread_id", "")
    if thread_id:
        sess = sess_store.get_active_for_channel(thread_id)
        if sess and sess.get("project_name") == project["name"] and sess.get("thread_id") == thread_id:
            return sess

    sessions = sess_store.list_thread_sessions(project_name=project["name"])
    if not sessions:
        if thread_id:
            proj_store.clear_active_thread(project["name"])
        return None

    sessions.sort(key=lambda r: (r.get("updated_at", ""), r.get("created_at", ""), r.get("id", "")))
    sess = sessions[-1]
    if sess.get("thread_id") and sess.get("thread_id") != thread_id:
        proj_store.set_active_thread(project["name"], sess["thread_id"])
    return sess


async def ensure_parent_thread_session(project: dict, parent_channel_id: str, user_id: str,
                                       thread_name: str = "", initial_message: str = "") -> tuple[dict, str, bool]:
    existing = get_active_thread_session(project)
    if existing and existing.get("thread_id"):
        return existing, existing["thread_id"], False

    name = (thread_name or "").strip() or f"{project['name']} session"
    opener = (initial_message or "").strip() or f"Continuing this Codex session from <#{parent_channel_id}>."
    created = await dh.create_thread_standalone(parent_channel_id, name, initial_message=opener)
    thread_id = created.get("thread_id", "")
    if not thread_id:
        raise RuntimeError("Failed to create session thread.")

    root_session = sess_store.get_active_root_for_project(project["name"])
    if root_session:
        sess_store.attach_channel(root_session["id"], thread_id, thread_id=thread_id)
        session = sess_store.get(root_session["id"]) or root_session
    else:
        session = sess_store.create(project["name"], thread_id, user_id, thread_id=thread_id)

    proj_store.set_active_channel(project["name"], parent_channel_id, thread_id)
    return session, thread_id, True


def clear_project_thread_for_session(session: dict | None):
    if not session or not session.get("project_name") or not session.get("thread_id"):
        return
    project = proj_store.get(session["project_name"])
    if not project:
        return
    if project.get("active_thread_id") == session["thread_id"]:
        proj_store.clear_active_thread(session["project_name"])
