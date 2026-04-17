import asyncio
import storage.projects as proj_store
import storage.sessions as sess_store
import layers.claude_exec as claude_exec
from layers.claude_exec import TurnLimitReached
from utils.discord_helpers import followup, followup_chunks, opts
import utils.discord_helpers as dh
from utils.security import truncate

# Per-session custom turn limits
_session_limits: dict[str, int] = {}

# Auto-continue sessions: {session_id: True}
_auto_continue: dict[str, bool] = {}

# Active bulk runs that can be cancelled: {channel_id: True}
_bulk_cancel: dict[str, bool] = {}


def _require_session(channel_id: str, user_id: str):
    proj = proj_store.get_by_channel(channel_id)
    if not proj:
        all_projects = proj_store.list_all()
        if all_projects:
            names = ", ".join(f"`{p['name']}`" for p in all_projects)
            raise ValueError(f"No active project in this channel.\nAvailable projects: {names}\nUse `/project use <name>` to select one.")
        else:
            raise ValueError("No projects registered. Use `/project add` to create one, then `/project use` to activate it.")
    sess = sess_store.get_active_for_channel(channel_id)
    if not sess:
        sess = sess_store.create(proj["name"], channel_id, user_id)
    return proj, sess


async def _run_with_progress(sess_id, prompt, proj_path, channel_id, followup_fn, followup_chunks_fn, token, max_turns=20):
    """Shared helper to run Claude with progress streaming and turn-limit handling."""
    progress_msgs = []
    def on_progress(msg: str):
        progress_msgs.append(msg)

    async def stream_progress():
        last_sent = 0
        while True:
            await asyncio.sleep(4)
            new = progress_msgs[last_sent:]
            if new:
                await followup_fn(token, "\n".join(new[-5:]))
                last_sent = len(progress_msgs)

    progress_task = asyncio.create_task(stream_progress())
    try:
        result = await claude_exec.run(
            session_id=sess_id,
            prompt=prompt,
            project_path=proj_path,
            progress_cb=on_progress,
            max_turns=max_turns,
            channel_id=channel_id,
        )
        return result, None
    except TurnLimitReached as e:
        return e.partial_result, e
    finally:
        progress_task.cancel()


async def handle(sub: str, sub_opts: list, token: str, channel_id: str, user_id: str,
                 followup_fn, followup_chunks_fn):
    o = opts(sub_opts)

    if sub == "ask":
        prompt = o.get("prompt", "")
        if not prompt:
            return await followup(token, "❌ `prompt` is required.")
        try:
            proj, sess = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")

        await followup(token, f"🤖 **Claude is working on it...**\nProject: `{proj['name']}`\nSession: `{sess['id']}`")

        max_turns = _session_limits.get(sess["id"], 20)
        result, exc = await _run_with_progress(
            sess["id"], prompt, proj["path"], channel_id,
            followup_fn, followup_chunks_fn, token, max_turns
        )

        if exc:
            if result:
                await followup_chunks_fn(token, result)
            summary = getattr(exc, 'task_summary', {})
            summary_text = ""
            if summary:
                summary_text = (
                    f"\n**Task Summary:**\n"
                    f"Requested: {summary.get('requested', 'N/A')}\n"
                    f"Completed: {summary.get('completed', 'N/A')}\n"
                    f"Remaining: {summary.get('remaining', 'N/A')}"
                )
            await followup_fn(token,
                f"⚠️ **Step limit reached ({max_turns} steps).**{summary_text}\n"
                f"Use `/claude continue` to keep going, `/claude auto` to auto-continue until done, "
                f"or `/claude limit steps:40` to increase the limit."
            )
            return

        await followup_chunks_fn(token, result)

    elif sub == "continue":
        prompt = o.get("prompt", "Continue where you left off.")
        try:
            proj, sess = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")
        if not sess_store.get_history(sess["id"]):
            return await followup(token,
                "❌ No previous work in this session — use `/claude ask` to start a task first.")
        last = sess.get("last_prompt", "(no previous prompt)")
        await followup(token, f"🔄 Continuing session `{sess['id']}`...\nLast: _{last[:100]}_")

        max_turns = _session_limits.get(sess["id"], 20)
        result, exc = await _run_with_progress(
            sess["id"], prompt, proj["path"], channel_id,
            followup_fn, followup_chunks_fn, token, max_turns
        )

        if exc:
            if result:
                await followup_chunks_fn(token, result)
            summary = getattr(exc, 'task_summary', {})
            remaining = summary.get('remaining', '') if summary else ''
            await followup_fn(token,
                f"⚠️ **Step limit reached again.**\n"
                f"Remaining: {remaining or 'unknown'}\n"
                f"Use `/claude continue` or `/claude auto` to keep going."
            )
            return

        await followup_chunks_fn(token, result)

    elif sub == "auto":
        prompt = o.get("prompt", "Continue where you left off.")
        max_rounds = int(o.get("rounds", 5))
        try:
            proj, sess = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")

        _auto_continue[sess["id"]] = True
        steps_per_round = _session_limits.get(sess["id"], 20)
        total_steps = 0

        await followup(token,
            f"🔁 **Auto-continue mode** — will run up to {max_rounds} rounds ({steps_per_round} steps each).\n"
            f"Say `stop` to cancel at any time.\nProject: `{proj['name']}`"
        )

        for round_num in range(1, max_rounds + 1):
            if not _auto_continue.get(sess["id"]):
                await followup_fn(token, "⛔ Auto-continue cancelled.")
                break

            round_prompt = prompt if round_num == 1 else "Continue where you left off. Complete the remaining tasks."
            await followup_fn(token, f"🔄 **Round {round_num}/{max_rounds}** (steps: {steps_per_round})")

            result, exc = await _run_with_progress(
                sess["id"], round_prompt, proj["path"], channel_id,
                followup_fn, followup_chunks_fn, token, steps_per_round
            )
            total_steps += steps_per_round

            if result:
                await followup_chunks_fn(token, result)

            if not exc:
                # Task completed naturally
                await followup_fn(token,
                    f"✅ **Auto-continue complete** — task finished in {round_num} round(s), ~{total_steps} steps."
                )
                break

            summary = getattr(exc, 'task_summary', {})
            remaining = summary.get('remaining', '') if summary else ''
            if remaining and ('nothing' in remaining.lower() or 'complete' in remaining.lower()):
                await followup_fn(token,
                    f"✅ **Task appears complete** after {round_num} round(s).\n"
                    f"Summary: {summary.get('summary', 'N/A')}"
                )
                break

            if round_num < max_rounds:
                await followup_fn(token,
                    f"⚠️ Round {round_num} hit step limit.\n"
                    f"Remaining: {remaining or 'unknown'}\nAuto-continuing..."
                )

        else:
            # All rounds exhausted
            await followup_fn(token,
                f"⚠️ **Auto-continue exhausted** ({max_rounds} rounds, ~{total_steps} steps).\n"
                f"Use `/claude auto rounds:10` for more, or `/claude continue` manually."
            )

        _auto_continue.pop(sess["id"], None)

    elif sub == "thread":
        prompt = o.get("prompt", "")
        name = o.get("name", "")
        if not prompt:
            return await followup(token, "❌ `prompt` is required.")
        try:
            proj, sess_parent = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")

        thread_name = name or prompt[:80]
        await followup(token, f"🧵 Creating thread: **{thread_name}**...")

        # Send an anchor message, then create thread from it
        anchor = await dh.send_message(channel_id, f"🧵 **{thread_name}**\nProject: `{proj['name']}`")
        anchor_id = anchor.get("id", "")
        if not anchor_id:
            return await followup(token, "❌ Failed to create anchor message for thread.")

        thread_id = await dh.create_thread(channel_id, anchor_id, thread_name)
        if not thread_id:
            return await followup(token, "❌ Failed to create thread.")

        # Create a new session scoped to the thread
        thread_sess = sess_store.create(proj["name"], thread_id, user_id, thread_id=thread_id)

        await dh.send_message(thread_id, f"🤖 **Claude is working on it...**\nSession: `{thread_sess['id']}`")

        try:
            result = await claude_exec.run(
                session_id=thread_sess["id"],
                prompt=prompt,
                project_path=proj["path"],
                channel_id=thread_id,
            )
        except TurnLimitReached as e:
            if e.partial_result:
                await dh.send_message_chunks(thread_id, e.partial_result)
            summary = getattr(e, 'task_summary', {})
            await dh.send_message(thread_id,
                f"⚠️ Step limit reached.\nRemaining: {summary.get('remaining', 'unknown')}\n"
                f"Use `/claude continue` in this thread to keep going."
            )
            return

        await dh.send_message_chunks(thread_id, result)
        await followup(token, f"✅ Thread complete: **{thread_name}**")

    elif sub == "bulk":
        prompt = o.get("prompt", "")
        count = int(o.get("count", 3))
        name_prefix = o.get("name", "Task")
        if not prompt:
            return await followup(token, "❌ `prompt` is required.")
        if count < 1 or count > 10:
            return await followup(token, "❌ Count must be between 1 and 10.")
        try:
            proj, _ = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")

        _bulk_cancel[channel_id] = False
        await followup(token,
            f"🔁 **Bulk mode** — creating {count} threads with prompt:\n> {prompt[:200]}\n"
            f"Say `stop` to cancel."
        )

        async def run_in_thread(idx: int):
            thread_name = f"{name_prefix} #{idx + 1}"
            anchor = await dh.send_message(channel_id, f"🧵 **{thread_name}**")
            anchor_id = anchor.get("id", "")
            if not anchor_id:
                return
            tid = await dh.create_thread(channel_id, anchor_id, thread_name)
            if not tid:
                return

            thread_sess = sess_store.create(proj["name"], tid, user_id, thread_id=tid)
            await dh.send_message(tid, f"🤖 Working on: {prompt[:200]}\nSession: `{thread_sess['id']}`")

            try:
                result = await claude_exec.run(
                    session_id=thread_sess["id"],
                    prompt=prompt,
                    project_path=proj["path"],
                    channel_id=tid,
                )
                await dh.send_message_chunks(tid, result)
                await dh.send_message(tid, "✅ Task complete.")
            except TurnLimitReached as e:
                if e.partial_result:
                    await dh.send_message_chunks(tid, e.partial_result)
                await dh.send_message(tid, "⚠️ Step limit reached. Use `/claude continue` here.")
            except Exception as e:
                await dh.send_message(tid, f"❌ Error: {str(e)[:200]}")

        # Run threads in parallel (max 3 concurrent)
        semaphore = asyncio.Semaphore(3)
        async def limited_run(idx):
            if _bulk_cancel.get(channel_id):
                return
            async with semaphore:
                await run_in_thread(idx)

        tasks = [asyncio.create_task(limited_run(i)) for i in range(count)]
        await asyncio.gather(*tasks, return_exceptions=True)

        _bulk_cancel.pop(channel_id, None)
        await followup_fn(token, f"✅ **Bulk run complete** — {count} threads finished.")

    elif sub == "diff":
        try:
            proj, sess = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")
        diff = await claude_exec.get_diff(proj["path"])
        if not diff.strip():
            return await followup(token, "No changes since last commit.")
        await followup_chunks_fn(token, diff, code_lang="diff")

    elif sub == "status":
        try:
            proj, sess = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")
        status = await claude_exec.get_status(proj["path"])
        hist_count = len(sess_store.get_history(sess["id"]))
        t = claude_exec.get_token_usage(sess["id"])

        # Include task summary if available
        task_sum = sess_store.get_task_summary(sess["id"])
        summary_text = ""
        if task_sum and task_sum.get("summary"):
            summary_text = (
                f"\n**Last task summary:**\n"
                f"Requested: {task_sum.get('task_requested', 'N/A')}\n"
                f"Completed: {task_sum.get('task_completed', 'N/A')}\n"
                f"Remaining: {task_sum.get('task_remaining', 'N/A')}"
            )

        await followup(token,
            f"**Session:** `{sess['id']}`\n"
            f"**Project:** `{proj['name']}`\n"
            f"**Messages:** {hist_count} | **Tokens** in: `{t['input']:,}` out: `{t['output']:,}`\n"
            f"**Git:**\n```\n{status}\n```"
            f"{summary_text}"
        )

    elif sub == "plan":
        prompt = o.get("prompt", "")
        if not prompt:
            return await followup(token, "❌ `prompt` is required.")
        try:
            proj, sess = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")
        full_prompt = f"Do NOT make any changes yet. Just analyze the codebase and give me a detailed plan for: {prompt}"
        result = await claude_exec.run(
            session_id=sess["id"],
            prompt=full_prompt,
            project_path=proj["path"],
        )
        await followup_chunks_fn(token, f"**Plan:**\n{result}")

    elif sub == "fix":
        prompt = o.get("prompt", "Fix any issues you find.")
        try:
            proj, sess = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")
        full_prompt = f"Find and fix the following issue: {prompt}. Run tests if a test suite exists."
        result = await claude_exec.run(
            session_id=sess["id"],
            prompt=full_prompt,
            project_path=proj["path"],
        )
        await followup_chunks_fn(token, f"**Fix result:**\n{result}")

    elif sub == "stop":
        try:
            proj, sess = _require_session(channel_id, user_id)
            # Cancel any auto-continue
            _auto_continue.pop(sess["id"], None)
            _bulk_cancel[channel_id] = True

            claude_exec.close_session_shell(sess["id"])
            sess_store.close(sess["id"])
            proj_store.clear_active_channel(channel_id)
            t = claude_exec.get_token_usage(sess["id"])
            await followup(token,
                f"✅ Session `{sess['id']}` closed.\n"
                f"Project `{proj['name']}` detached from this channel.\n"
                f"Tokens used — input: `{t['input']:,}` output: `{t['output']:,}`\n"
                f"Use `/project use <name>` to start a new session."
            )
        except ValueError as e:
            await followup(token, f"❌ {e}")

    elif sub == "limit":
        steps = int(o.get("steps", 40))
        try:
            proj, sess = _require_session(channel_id, user_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")
        _session_limits[sess["id"]] = steps
        await followup(token, f"✅ Step limit set to **{steps}** for session `{sess['id']}`.")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
