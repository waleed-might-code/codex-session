"""
Handles all /server subcommands:
  list, test, add, add-key, use, bootstrap
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import storage
import ssh_helper


def _safe_host_display(host: dict) -> str:
    """Display host info without exposing credentials."""
    default_tag = " ⭐ default" if host.get("is_default") else ""
    auth_method = "🔑 key" if host.get("ssh_key") else "🔐 password"
    status_icon = {"healthy": "🟢", "unhealthy": "🔴"}.get(host.get("status", ""), "⚪")
    return f"{status_icon} `{host['host']}` — user: `{host['username']}` — auth: {auth_method}{default_tag}"


async def handle(subcommand: str, options: list, respond) -> str:
    opts = {o["name"]: o["value"] for o in options}

    # ── /server list ──────────────────────────────────────────────────────────
    if subcommand == "list":
        hosts = storage.list_hosts()
        if not hosts:
            return "No servers configured yet. Use `/server add` to add one."
        lines = ["**Configured Servers:**"]
        for h in hosts:
            lines.append(_safe_host_display(h))
        return "\n".join(lines)

    # ── /server test ──────────────────────────────────────────────────────────
    elif subcommand == "test":
        host_id = opts.get("host")
        if host_id:
            host = storage.get_host(host_id)
            if not host:
                return f"❌ No server found with host `{host_id}`."
        else:
            host = storage.get_default_host()
            if not host:
                return "❌ No default server set."

        await respond(f"🔄 Testing connection to `{host['host']}`...")
        result = ssh_helper.test_connection(host)
        status = "healthy" if result["ok"] else "unhealthy"
        storage.update_host(host["id"], status=status)

        if result["ok"]:
            return f"✅ `{host['host']}` is reachable.\n{result['message']}"
        else:
            return f"❌ `{host['host']}` failed: {result['message']}"

    # ── /server add ───────────────────────────────────────────────────────────
    elif subcommand == "add":
        host = opts.get("host")
        username = opts.get("username", "root")
        password = opts.get("password")
        if not host:
            return "❌ `host` is required."
        storage.add_host(host, username, password=password)
        return f"✅ Added server `{host}` (user: `{username}`). Run `/server test host:{host}` to verify."

    # ── /server add-key ───────────────────────────────────────────────────────
    elif subcommand == "add-key":
        host = opts.get("host")
        username = opts.get("username", "root")
        ssh_key = opts.get("key")
        if not host or not ssh_key:
            return "❌ `host` and `key` are required."
        storage.add_host(host, username, ssh_key=ssh_key)
        return f"✅ Added server `{host}` with SSH key auth."

    # ── /server use ───────────────────────────────────────────────────────────
    elif subcommand == "use":
        host_id = opts.get("host")
        if not host_id:
            return "❌ `host` is required."
        host = storage.get_host(host_id)
        if not host:
            return f"❌ No server found with host `{host_id}`."
        storage.set_default_host(host["id"])
        return f"✅ Default server set to `{host['host']}`."

    # ── /server bootstrap ────────────────────────────────────────────────────
    elif subcommand == "bootstrap":
        host_id = opts.get("host")
        host = storage.get_host(host_id) if host_id else storage.get_default_host()
        if not host:
            return "❌ No server found."

        await respond(f"🔄 Bootstrapping `{host['host']}` — creating deploy user and installing SSH key...")
        result = ssh_helper.bootstrap_host(host)

        if result["ok"]:
            # Save the generated private key and update username to deploy
            storage.update_host(host["id"], username="deploy", ssh_key=result["private_key"], password=None)
            return f"✅ Bootstrap complete for `{host['host']}`.\nDeploy user created with key-based auth. Password auth no longer needed."
        else:
            return f"⚠️ Bootstrap partially failed: {result['message']}"

    return f"❌ Unknown subcommand: `{subcommand}`"
