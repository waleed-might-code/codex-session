"""
Handles /deploy subcommands: api, full
Deploys services to the default (or specified) host.
Ports are auto-assigned starting at 5022, persisted for reuse.
Services are bound to 127.0.0.1 and exposed via Cloudflare Tunnel.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import storage
import ssh_helper


async def handle(subcommand: str, options: list, respond) -> str:
    opts = {o["name"]: o["value"] for o in options}

    host_id = opts.get("server")
    host = storage.get_host(host_id) if host_id else storage.get_default_host()
    if not host:
        return "❌ No server configured. Use `/server add` first."

    # ── /deploy api ───────────────────────────────────────────────────────────
    if subcommand == "api":
        repo = opts.get("repo")
        branch = opts.get("branch", "main")
        service = opts.get("service", "api")

        await respond(f"🚀 Deploying `{service}` to `{host['host']}`...")

        # Find or reuse port
        port = ssh_helper.find_free_port(host, service)
        await respond(f"📡 Using port `{port}` for `{service}`...")

        steps = []

        # Ensure dependencies
        out, err, code = ssh_helper.run_command(host,
            "which git python3 pip3 || apt-get install -y git python3 python3-pip 2>&1 | tail -3"
        )
        steps.append(f"**Deps:** {'✅' if code == 0 else '⚠️'}")

        # Detect best python on remote: prefer pyenv, fall back to system
        py_out, _, _ = ssh_helper.run_command(host, "bash -lc 'which python' 2>/dev/null || which python3")
        remote_python = py_out.strip().split("\\n")[-1] or "/usr/bin/python3"

        deploy_dir = f"/home/deploy/services/{service}"

        if repo:
            # Clone or pull repo
            out, err, code = ssh_helper.run_command(host,
                f"mkdir -p /home/deploy/services && "
                f"if [ -d {deploy_dir} ]; then cd {deploy_dir} && git pull origin {branch}; "
                f"else git clone --branch {branch} {repo} {deploy_dir}; fi"
            )
            steps.append(f"**Git:** {'✅' if code == 0 else f'❌ {err[:100]}'}")

            # Install requirements
            out, err, code = ssh_helper.run_command(host,
                f"cd {deploy_dir} && [ -f requirements.txt ] && pip3 install -r requirements.txt -q || true"
            )
            steps.append(f"**Pip:** {'✅' if code == 0 else f'⚠️ {err[:80]}'}")
        else:
            steps.append("**Repo:** skipped (no repo provided)")

        # Create/update systemd service
        service_file = f"""[Unit]
Description={service} service
After=network.target

[Service]
WorkingDirectory={deploy_dir}
ExecStart={remote_python} -m uvicorn main:app --host 127.0.0.1 --port {port}
Restart=always
RestartSec=5
Environment=PORT={port}

[Install]
WantedBy=multi-user.target
"""
        write_cmd = f"cat > /etc/systemd/system/{service}.service << 'SYSTEMD_EOF'\n{service_file}\nSYSTEMD_EOF"
        out, err, code = ssh_helper.run_command(host, write_cmd)

        out, err, code = ssh_helper.run_command(host,
            f"systemctl daemon-reload && systemctl enable {service} && systemctl restart {service}"
        )
        steps.append(f"**Systemd:** {'✅ running' if code == 0 else f'❌ {err[:100]}'}")

        summary = "\n".join(steps)
        return (
            f"**Deploy complete:** `{service}` on `{host['host']}`\n"
            f"{summary}\n"
            f"🔒 Bound to `127.0.0.1:{port}` — expose with `/deploy tunnel service:{service}`"
        )

    # ── /deploy full ──────────────────────────────────────────────────────────
    elif subcommand == "full":
        await respond(f"🚀 Full deploy to `{host['host']}`...")
        results = []

        for svc in ["api", "worker"]:
            port = ssh_helper.find_free_port(host, svc)
            out, err, code = ssh_helper.run_command(host,
                f"systemctl is-active {svc} 2>/dev/null || echo inactive"
            )
            status = out.strip()
            results.append(f"`{svc}` → port `{port}` — status: `{status}`")

        return "**Full deploy status:**\n" + "\n".join(results)

    # ── /deploy tunnel ────────────────────────────────────────────────────────
    elif subcommand == "tunnel":
        service = opts.get("service", "api")
        port = storage.get_service_port(service, host["id"])
        if not port:
            return f"❌ No port found for `{service}`. Deploy it first with `/deploy api`."

        await respond(f"🌐 Setting up Cloudflare Tunnel for `{service}` on port `{port}`...")

        # Install cloudflared if needed
        out, err, code = ssh_helper.run_command(host,
            "which cloudflared || (curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared)"
        )

        # Run quick tunnel (no auth needed)
        out, err, code = ssh_helper.run_command(host,
            f"nohup cloudflared tunnel --url http://127.0.0.1:{port} --no-autoupdate > /tmp/{service}_tunnel.log 2>&1 & sleep 4 && grep -o 'https://[^ ]*trycloudflare.com' /tmp/{service}_tunnel.log | head -1"
        )
        tunnel_url = out.strip()
        if tunnel_url:
            return f"✅ Tunnel active for `{service}`:\n🔗 {tunnel_url}"
        else:
            return f"⚠️ Tunnel started but URL not yet available. Check `/tmp/{service}_tunnel.log` on the server."

    # ── /deploy status ────────────────────────────────────────────────────────
    elif subcommand == "status":
        await respond(f"🔍 Checking services on `{host['host']}`...")
        out, err, code = ssh_helper.run_command(host,
            "systemctl list-units --type=service --state=running --no-pager --no-legend | grep -v systemd | head -20"
        )
        if not out:
            return f"No running services found on `{host['host']}`."
        return f"**Running services on `{host['host']}`:**\n```\n{out}\n```"

    return f"❌ Unknown subcommand: `{subcommand}`"
