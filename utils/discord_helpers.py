"""
Discord HTTP helpers: defer, followup, send file, chunk long messages.
"""
import asyncio
import base64
import io
import os
import httpx

API = "https://discord.com/api/v10"
_TOKEN = None
_APP_ID = None


def init(token: str):
    global _TOKEN, _APP_ID
    _TOKEN = token
    _APP_ID = base64.b64decode(token.split(".")[0] + "==").decode()


def _headers():
    return {"Authorization": f"Bot {_TOKEN}"}


async def defer(interaction_id: str, token: str, ephemeral: bool = False):
    flags = 64 if ephemeral else 0
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"{API}/interactions/{interaction_id}/{token}/callback",
            json={"type": 5, "data": {"flags": flags}},
            headers=_headers(),
        )
        if r.status_code not in (200, 204):
            print(f"[defer] failed: {r.status_code} {r.text[:200]}")


async def respond(interaction_id: str, token: str, content: str):
    """Non-deferred immediate response."""
    async with httpx.AsyncClient() as c:
        await c.post(
            f"{API}/interactions/{interaction_id}/{token}/callback",
            json={"type": 4, "data": {"content": content[:2000]}},
            headers=_headers(),
        )


async def followup(token: str, content: str, file_bytes: bytes = None, filename: str = None) -> dict:
    url = f"{API}/webhooks/{_APP_ID}/{token}"
    async with httpx.AsyncClient(timeout=30) as c:
        if file_bytes:
            files = {"file": (filename or "output.txt", file_bytes)}
            data = {"content": content[:1990]} if content else {}
            r = await c.post(url, data=data, files=files, headers=_headers())
        else:
            r = await c.post(url, json={"content": content[:2000]}, headers=_headers())
    return r.json() if r.content else {}


async def followup_chunks(token: str, text: str, code_lang: str = ""):
    """Send long text as multiple follow-up messages."""
    from utils.security import chunk_message
    wrap = f"```{code_lang}\n" if code_lang else ""
    wrap_end = "```" if code_lang else ""
    limit = 1900 - len(wrap) - len(wrap_end)
    chunks = chunk_message(text, size=limit)
    for chunk in chunks:
        await followup(token, f"{wrap}{chunk}{wrap_end}")
        await asyncio.sleep(0.3)


async def send_image_to_channel(channel_id: str, image_bytes: bytes, filename: str = "screenshot.png", caption: str = ""):
    url = f"{API}/channels/{channel_id}/messages"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            url,
            data={"content": caption},
            files={"file": (filename, image_bytes, "image/png")},
            headers=_headers(),
        )
    return r.json()


async def send_message(channel_id: str, content: str) -> dict:
    url = f"{API}/channels/{channel_id}/messages"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json={"content": content[:2000]}, headers=_headers())
    return r.json() if r.content else {}


async def send_file(channel_id: str, file_bytes: bytes, filename: str,
                    caption: str = "", content_type: str = "application/octet-stream") -> dict:
    """Send any file to a Discord channel as an attachment."""
    url = f"{API}/channels/{channel_id}/messages"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            url,
            data={"content": caption[:2000]} if caption else {},
            files={"file": (filename, file_bytes, content_type)},
            headers=_headers(),
        )
    return r.json() if r.content else {}


async def send_message_chunks(channel_id: str, text: str, code_lang: str = ""):
    from utils.security import chunk_message
    wrap = f"```{code_lang}\n" if code_lang else ""
    wrap_end = "```" if code_lang else ""
    limit = 1900 - len(wrap) - len(wrap_end)
    for chunk in chunk_message(text, size=limit):
        await send_message(channel_id, f"{wrap}{chunk}{wrap_end}")
        await asyncio.sleep(0.3)


async def send_typing(channel_id: str):
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{API}/channels/{channel_id}/typing", headers=_headers())


async def get_channel(channel_id: str) -> dict:
    """Fetch channel info (type, parent_id, etc.)."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API}/channels/{channel_id}", headers=_headers())
    return r.json() if r.status_code == 200 else {}


async def resolve_thread_parent(channel_id: str) -> str:
    """If channel_id is a thread (type 11/12), return its parent channel id; else return channel_id."""
    ch = await get_channel(channel_id)
    ch_type = ch.get("type", 0)
    if ch_type in (10, 11, 12):  # ANNOUNCEMENT_THREAD, PUBLIC_THREAD, PRIVATE_THREAD
        parent = ch.get("parent_id", channel_id)
        print(f"[resolve_thread_parent] {channel_id} is a thread, using parent {parent}")
        return parent
    return channel_id


async def create_thread(channel_id: str, message_id: str, name: str) -> str:
    import asyncio as _asyncio
    url = f"{API}/channels/{channel_id}/messages/{message_id}/threads"
    payload = {"name": name[:100], "auto_archive_duration": 1440}
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(url, json=payload, headers=_headers())
        if r.status_code == 201:
            return r.json().get("id", "")
        if r.status_code == 429:
            retry_after = r.json().get("retry_after", 5)
            print(f"[create_thread] rate limited — waiting {retry_after}s (attempt {attempt+1})")
            await _asyncio.sleep(float(retry_after) + 0.5)
            continue
        print(f"[create_thread] FAILED {r.status_code}: {r.text[:300]}")
        return ""
    print(f"[create_thread] gave up after 3 attempts for: {name}")
    return ""


async def create_thread_standalone(channel_id: str, name: str, initial_message: str = "") -> dict:
    """Create a thread in a text channel without an existing message (no anchor post in channel)."""
    import asyncio as _asyncio
    payload = {
        "name": name[:100],
        "type": 11,  # PUBLIC_THREAD
        "auto_archive_duration": 1440,
    }
    if initial_message:
        payload["message"] = {"content": initial_message[:2000]}
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{API}/channels/{channel_id}/threads", json=payload, headers=_headers())
        if r.status_code == 201:
            data = r.json()
            return {"thread_id": data.get("id", ""), "name": data.get("name", name)}
        if r.status_code == 429:
            retry_after = r.json().get("retry_after", 5)
            print(f"[create_thread_standalone] rate limited — waiting {retry_after}s (attempt {attempt+1})")
            await _asyncio.sleep(float(retry_after) + 0.5)
            continue
        print(f"[create_thread_standalone] FAILED {r.status_code}: {r.text[:300]}")
        return {"thread_id": "", "name": name}
    print(f"[create_thread_standalone] gave up after 3 attempts for: {name}")
    return {"thread_id": "", "name": name}


def opts(options: list) -> dict:
    """Flatten interaction options list to {name: value} dict, handling subcommand groups."""
    result = {}
    for o in options:
        if o.get("type") in (1, 2):  # subcommand / group — recurse
            result.update(opts(o.get("options", [])))
        else:
            result[o["name"]] = o["value"]
    return result


def subcommand(options: list) -> tuple[str, list]:
    """Extract (subcommand_name, sub_options) from interaction options."""
    if not options:
        return "", []
    first = options[0]
    if first.get("type") in (1, 2):
        return first["name"], first.get("options", [])
    return "", options
