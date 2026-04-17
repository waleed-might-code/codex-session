import storage.servers as srv_store
import layers.ssh_layer as ssh
from utils.discord_helpers import followup, followup_chunks, opts
from utils.security import truncate


def _fmt(server: dict) -> str:
    default = " ⭐" if server.get("is_default") == "true" else ""
    status_icon = {"healthy": "🟢", "unhealthy": "🔴"}.get(server.get("status", ""), "⚪")
    auth = "🔑 key" if server.get("auth_type") == "key" else "🔐 password"
    return f"{status_icon} **{server['name']}** — `{server['host']}` — {server['username']} — {auth}{default}"


async def handle(sub: str, sub_opts: list, token: str):
    o = opts(sub_opts)

    if sub == "add":
        name = o.get("name", "")
        host = o.get("host", "")
        username = o.get("username", "root")
        password = o.get("password", "")
        if not name or not host:
            return await followup(token, "❌ `name` and `host` are required.")
        srv_store.add(name, host, username, password=password)
        await followup(token, f"✅ Server **{name}** added (`{host}`).\nRun `/server test name:{name}` to verify.")

    elif sub == "add-key":
        name = o.get("name", "")
        host = o.get("host", "")
        username = o.get("username", "root")
        key = o.get("private_key", "")
        if not name or not host or not key:
            return await followup(token, "❌ `name`, `host`, and `private_key` are required.")
        srv_store.add(name, host, username, ssh_key=key)
        await followup(token, f"✅ Server **{name}** added with SSH key auth.")

    elif sub == "list":
        servers = srv_store.list_all()
        if not servers:
            return await followup(token, "No servers configured. Use `/server add`.")
        lines = ["**Servers:**"] + [_fmt(s) for s in servers]
        await followup(token, "\n".join(lines))

    elif sub == "test":
        name = o.get("name", "")
        server = srv_store.get(name) if name else srv_store.get_default()
        if not server:
            return await followup(token, f"❌ Server `{name or 'default'}` not found.")
        await followup(token, f"🔄 Testing `{server['host']}`...")
        result = await ssh.run_async(server, "uname -a && df -h / | tail -1 && free -h | head -2")
        out, err, code = result
        status = "healthy" if code == 0 else "unhealthy"
        srv_store.update_status(server["name"], status)
        icon = "✅" if code == 0 else "❌"
        await followup(token, f"{icon} **{server['name']}** (`{server['host']}`) — {status}\n```\n{out or err}\n```")

    elif sub == "use":
        name = o.get("name", "")
        if not srv_store.get(name):
            return await followup(token, f"❌ Server `{name}` not found.")
        srv_store.set_default(name)
        await followup(token, f"✅ Default server set to **{name}**.")

    elif sub == "logs":
        name = o.get("name", "")
        service = o.get("service", "")
        tail = int(o.get("tail_lines", 50))
        server = srv_store.get(name) if name else srv_store.get_default()
        if not server:
            return await followup(token, "❌ Server not found.")
        if not service:
            return await followup(token, "❌ `service` is required.")
        await followup(token, f"📋 Fetching logs for `{service}` on `{server['host']}`...")
        logs = await ssh.run_async(server, f"journalctl -u {service} --no-pager -n {tail} 2>&1")
        out = logs[0] or logs[1]
        await followup_chunks(token, truncate(out, 3500), code_lang="")

    elif sub == "bootstrap":
        name = o.get("name", "")
        server = srv_store.get(name) if name else srv_store.get_default()
        if not server:
            return await followup(token, "❌ Server not found.")
        await followup(token, f"🔐 Bootstrapping `{server['host']}`...\nCreating deploy user + installing SSH key.")
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: ssh.bootstrap(server))
        if result["ok"]:
            srv_store.update_key(server["name"], "deploy", result["private_key"])
            await followup(token, f"✅ Bootstrap complete for `{server['host']}`.\nNow using `deploy` user with key auth.")
        else:
            await followup(token, f"⚠️ Bootstrap failed: {result['message']}")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
