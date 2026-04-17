from datetime import datetime, timezone

import storage.discord_jobs as jobs_store
from utils.discord_helpers import followup, opts
import utils.discord_helpers as dh


def _parse_run_at(raw: str) -> datetime:
    cleaned = raw.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def handle(sub: str, sub_opts: list, token: str, channel_id: str, user_id: str):
    o = opts(sub_opts)

    if sub == "send":
        content = o.get("message", "")
        if not content:
            return await followup(token, "❌ `message` is required.")
        target = o.get("channel", channel_id) or channel_id
        result = await dh.send_message(target, content)
        await followup(token, f"✅ Message sent to `{target}` as `{result.get('id', 'unknown')}`.")

    elif sub == "schedule":
        content = o.get("message", "")
        if not content:
            return await followup(token, "❌ `message` is required.")
        target = o.get("channel", channel_id) or channel_id
        delay_minutes = int(o.get("minutes", 0) or 0)
        at = o.get("at", "")
        if at:
            job = jobs_store.schedule(target, content, _parse_run_at(at), creator_user_id=user_id)
        else:
            job = jobs_store.schedule_after_seconds(target, content, delay_minutes * 60, creator_user_id=user_id)
        await followup(token,
            f"✅ Scheduled message `{job['id']}` for `{job['run_at']}` in channel `{target}`."
        )

    elif sub == "jobs":
        status = o.get("status", "")
        rows = jobs_store.list_jobs(channel_id=channel_id, status=status, limit=20)
        if not rows:
            return await followup(token, "No scheduled Discord jobs for this channel.")
        lines = ["**Scheduled Discord Jobs:**"]
        for row in rows:
            lines.append(
                f"• `{row['id']}` — `{row['status']}` at `{row['run_at']}`"
            )
        await followup(token, "\n".join(lines))

    elif sub == "cancel":
        job_id = o.get("id", "")
        if not job_id:
            return await followup(token, "❌ `id` is required.")
        jobs_store.cancel(job_id)
        await followup(token, f"✅ Cancelled Discord job `{job_id}`.")

    elif sub == "thread":
        name = o.get("name", "")
        if not name:
            return await followup(token, "❌ `name` is required.")
        message = o.get("message", "")
        target = o.get("channel", channel_id) or channel_id
        result = await dh.create_thread_standalone(target, name, initial_message=message)
        if not result.get("thread_id"):
            return await followup(token, "❌ Failed to create thread.")
        await followup(token, f"✅ Created thread `{result['name']}` as `{result['thread_id']}`.")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
