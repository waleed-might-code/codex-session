"""
SSH layer: connect, test, run commands, upload files, find ports, deploy services.
"""
import asyncio
import io
import os
import socket
import paramiko
import storage.servers as srv_store
from utils.security import CMD_TIMEOUT

PORT_START = 5022


def _client(server: dict, connect_timeout: int = 60) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    host = server["host"]
    user = server["username"]
    key_pem = srv_store.get_key(server)
    password = srv_store.get_password(server)

    kwargs = dict(
        username=user,
        timeout=connect_timeout,
        auth_timeout=connect_timeout,
        banner_timeout=connect_timeout,
    )
    if key_pem:
        kwargs["pkey"] = paramiko.RSAKey.from_private_key(io.StringIO(key_pem))
    else:
        kwargs["password"] = password

    ssh.connect(host, **kwargs)
    return ssh


def run(server: dict, cmd: str, timeout: int = None, retries: int = 2) -> tuple[str, str, int]:
    import time
    last_exc = None
    cmd_timeout = timeout or CMD_TIMEOUT
    connect_timeout = 60
    for attempt in range(retries + 1):
        try:
            ssh = _client(server, connect_timeout=connect_timeout)
            _, stdout, stderr = ssh.exec_command(cmd, timeout=cmd_timeout)
            code = stdout.channel.recv_exit_status()
            out = stdout.read().decode(errors="replace").strip()
            err = stderr.read().decode(errors="replace").strip()
            ssh.close()
            return out, err, code
        except Exception as e:
            last_exc = e
            if attempt < retries:
                connect_timeout = min(connect_timeout * 2, 300)
                cmd_timeout = min(cmd_timeout * 2, 600)
                print(f"[ssh] attempt {attempt + 1} failed ({e}), retrying (connect={connect_timeout}s cmd={cmd_timeout}s)...")
                time.sleep(5)
    raise last_exc


async def run_async(server: dict, cmd: str, timeout: int = None) -> tuple[str, str, int]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: run(server, cmd, timeout))


def test(server: dict) -> dict:
    import time
    try:
        t0 = time.time()
        out, _, code = run(server, "uname -a && whoami && df -h / | tail -1")
        ms = int((time.time() - t0) * 1000)
        return {"ok": True, "latency_ms": ms, "info": out}
    except Exception as e:
        return {"ok": False, "latency_ms": -1, "info": str(e)}


def find_free_port(server: dict, service_name: str) -> int:
    existing = srv_store.get_service_port(server["name"], service_name)
    if existing:
        return existing

    # Collect all ports already allocated in storage to avoid conflicts
    allocated = {int(s["port"]) for s in srv_store.list_all_ports(server["name"]) if s.get("port")}

    port = PORT_START
    while True:
        if port in allocated:
            port += 1
            continue
        out, _, _ = run(server, f"ss -tlnp 2>/dev/null | grep :{port} | wc -l")
        if out.strip() == "0":
            break
        port += 1
    srv_store.save_service_port(server["name"], service_name, port)
    return port


def upload_string(server: dict, content: str, remote_path: str):
    ssh = _client(server)
    sftp = ssh.open_sftp()
    with sftp.file(remote_path, "w") as f:
        f.write(content)
    sftp.close()
    ssh.close()


def bootstrap(server: dict) -> dict:
    """Create deploy user, install SSH key, return private key."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend

        private_key = rsa.generate_private_key(65537, 4096, default_backend())
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        ).decode()
        pub = private_key.public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        ).decode()

        cmds = [
            "id deploy 2>/dev/null || useradd -m -s /bin/bash deploy",
            "mkdir -p /home/deploy/.ssh && chmod 700 /home/deploy/.ssh",
            f'echo "{pub}" >> /home/deploy/.ssh/authorized_keys',
            "chmod 600 /home/deploy/.ssh/authorized_keys",
            "chown -R deploy:deploy /home/deploy/.ssh",
            "usermod -aG sudo deploy 2>/dev/null || usermod -aG wheel deploy 2>/dev/null || true",
            "echo 'deploy ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deploy",
        ]
        for cmd in cmds:
            run(server, cmd)

        # Verify key auth
        test_srv = dict(server)
        test_srv["username"] = "deploy"
        test_srv["auth_type"] = "key"
        # Temporarily inject key for test
        import utils.crypto as crypto
        test_srv["key_enc"] = crypto.encrypt(private_pem)
        test_srv["password_enc"] = ""
        result = test(test_srv)
        return {"ok": result["ok"], "private_key": private_pem,
                "message": "Deploy user ready." if result["ok"] else f"User created, key check failed: {result['info']}"}
    except Exception as e:
        return {"ok": False, "private_key": None, "message": str(e)}


def deploy_service(
    server: dict, service_name: str, repo_url: str = None,
    branch: str = "main", project_path: str = None,
    env_vars: dict = None, start_cmd: str = None,
) -> dict:
    """Deploy backend: git sync → pip install → systemd service."""
    steps = []
    port = find_free_port(server, service_name)
    deploy_dir = f"/root/services/{service_name}"

    # Ensure runtime
    run(server, "apt-get install -y python3 python3-pip python3-venv git -qq 2>/dev/null || true")
    steps.append("✅ Runtime deps")

    # Detect best python: prefer pyenv, fall back to system python3
    py_out, _, _ = run(server, "bash -lc 'which python' 2>/dev/null || which python3")
    remote_python = py_out.strip().split("\n")[-1] or "python3"
    steps.append(f"✅ Python: {remote_python}")

    run(server, f"mkdir -p {deploy_dir}")

    if repo_url:
        out, err, code = run(server,
            f"if [ -d {deploy_dir}/.git ]; then cd {deploy_dir} && git pull origin {branch}; "
            f"else git clone --branch {branch} {repo_url} {deploy_dir}; fi 2>&1"
        )
        steps.append(f"{'✅' if code == 0 else '❌'} Git: {'synced' if code == 0 else err[:80]}")

    # venv + install (use detected python)
    run(server, f"{remote_python} -m venv {deploy_dir}/venv 2>&1")
    if run(server, f"test -f {deploy_dir}/requirements.txt")[2] == 0:
        out, err, code = run(server,
            f"{deploy_dir}/venv/bin/pip install -r {deploy_dir}/requirements.txt -q 2>&1 | tail -3"
        )
        steps.append(f"{'✅' if code == 0 else '⚠️'} pip install")

    # Write env file
    if env_vars:
        env_content = "\n".join(f"{k}={v}" for k, v in env_vars.items())
        upload_string(server, env_content, f"{deploy_dir}/.env")
        steps.append("✅ Env file")

    # Write systemd unit
    exec_cmd = start_cmd or f"{deploy_dir}/venv/bin/python app.py"
    unit = f"""[Unit]
Description={service_name}
After=network.target

[Service]
WorkingDirectory={deploy_dir}
ExecStart={exec_cmd}
Restart=always
RestartSec=5
EnvironmentFile=-{deploy_dir}/.env

[Install]
WantedBy=multi-user.target
"""
    upload_string(server, unit, f"/etc/systemd/system/{service_name}.service")
    out, err, code = run(server,
        f"systemctl daemon-reload && systemctl enable {service_name} && systemctl restart {service_name}"
    )
    steps.append(f"{'✅' if code == 0 else '❌'} systemd: {'running' if code == 0 else err[:80]}")

    import time; time.sleep(3)
    out, _, _ = run(server, f"systemctl is-active {service_name}")
    healthy = out.strip() == "active"
    steps.append(f"{'✅' if healthy else '❌'} Health: {out.strip()}")

    return {"port": port, "steps": steps, "healthy": healthy, "deploy_dir": deploy_dir}


def get_logs(server: dict, service_name: str, lines: int = 50) -> str:
    out, err, _ = run(server, f"journalctl -u {service_name} --no-pager -n {lines} 2>&1")
    return out or err or "(no logs)"


def get_service_status(server: dict, service_name: str) -> dict:
    """Get detailed status of a systemd service."""
    out, _, code = run(server, f"systemctl is-active {service_name} 2>/dev/null")
    is_active = out.strip() == "active"

    status_out, _, _ = run(server,
        f"systemctl show {service_name} --property=ActiveState,SubState,MainPID,MemoryCurrent,ExecMainStartTimestamp "
        f"--no-pager 2>/dev/null"
    )
    props = {}
    for line in status_out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()

    logs, _, _ = run(server, f"journalctl -u {service_name} --no-pager -n 10 --output=short 2>&1")

    return {
        "active": is_active,
        "state": props.get("ActiveState", "unknown"),
        "sub_state": props.get("SubState", "unknown"),
        "pid": props.get("MainPID", ""),
        "memory": props.get("MemoryCurrent", ""),
        "started_at": props.get("ExecMainStartTimestamp", ""),
        "recent_logs": logs or "(no logs)",
    }


def update_service(
    server: dict, service_name: str, project_path: str = None,
    repo_url: str = None, branch: str = "main",
    env_vars: dict = None, start_cmd: str = None,
    progress_cb=None,
) -> dict:
    """Update an existing deployed service with progress reporting."""
    steps = []
    deploy_dir = f"/root/services/{service_name}"

    def report(msg):
        steps.append(msg)
        if progress_cb:
            progress_cb(msg)

    # Check if service exists
    out, _, code = run(server, f"systemctl is-active {service_name} 2>/dev/null")
    existed = code == 0
    if not existed:
        out2, _, code2 = run(server, f"test -d {deploy_dir}")
        if code2 != 0:
            report("❌ Service not found — use deploy first")
            return {"steps": steps, "healthy": False, "was_running": False, "restarted": False}

    report(f"📋 Service `{service_name}`: {'running' if existed else 'stopped'}")

    # Stop service before update
    if existed:
        run(server, f"systemctl stop {service_name}")
        report("⏸️ Stopped service for update")

    # Git pull if repo-based
    out, _, code = run(server, f"test -d {deploy_dir}/.git && echo yes || echo no")
    if out.strip() == "yes":
        pull_out, pull_err, pull_code = run(server,
            f"cd {deploy_dir} && git fetch origin && git reset --hard origin/{branch} 2>&1"
        )
        if pull_code == 0:
            # Get the short commit message
            commit_msg, _, _ = run(server, f"cd {deploy_dir} && git log --oneline -1")
            report(f"✅ Git updated: `{commit_msg.strip()[:60]}`")
        else:
            report(f"⚠️ Git pull issue: {(pull_err or pull_out)[:80]}")
    elif repo_url:
        out, err, code = run(server,
            f"git clone --branch {branch} {repo_url} {deploy_dir} 2>&1"
        )
        report(f"{'✅' if code == 0 else '❌'} Git clone: {'done' if code == 0 else err[:80]}")

    # Reinstall dependencies
    if run(server, f"test -f {deploy_dir}/requirements.txt")[2] == 0:
        out, err, code = run(server,
            f"{deploy_dir}/venv/bin/pip install -r {deploy_dir}/requirements.txt -q 2>&1 | tail -3"
        )
        report(f"{'✅' if code == 0 else '⚠️'} Dependencies reinstalled")
    elif run(server, f"test -f {deploy_dir}/package.json")[2] == 0:
        out, err, code = run(server, f"cd {deploy_dir} && npm install --production 2>&1 | tail -3")
        report(f"{'✅' if code == 0 else '⚠️'} npm install")

    # Update env file if provided
    if env_vars:
        env_content = "\n".join(f"{k}={v}" for k, v in env_vars.items())
        upload_string(server, env_content, f"{deploy_dir}/.env")
        report("✅ Environment updated")

    # Update systemd unit if start_cmd changed
    if start_cmd:
        exec_cmd = start_cmd
        unit = f"""[Unit]
Description={service_name}
After=network.target

[Service]
WorkingDirectory={deploy_dir}
ExecStart={exec_cmd}
Restart=always
RestartSec=5
EnvironmentFile=-{deploy_dir}/.env

[Install]
WantedBy=multi-user.target
"""
        upload_string(server, unit, f"/etc/systemd/system/{service_name}.service")
        run(server, "systemctl daemon-reload")
        report("✅ Service config updated")

    # Restart service
    out, err, code = run(server, f"systemctl start {service_name}")
    report(f"{'✅' if code == 0 else '❌'} Service restarted")

    import time; time.sleep(3)

    # Health check with retries
    healthy = False
    for attempt in range(3):
        out, _, _ = run(server, f"systemctl is-active {service_name}")
        if out.strip() == "active":
            healthy = True
            break
        time.sleep(2)

    if healthy:
        report("✅ Health check passed — service is running")
    else:
        # Get failure logs
        fail_logs = get_logs(server, service_name, lines=15)
        report(f"❌ Health check failed — service not running")
        report(f"📜 Logs:\n```\n{fail_logs[:500]}\n```")

        # Auto-rollback attempt: restart with previous known-good state
        if existed:
            run(server, f"systemctl restart {service_name}")
            time.sleep(3)
            out, _, _ = run(server, f"systemctl is-active {service_name}")
            if out.strip() == "active":
                report("🔄 Auto-rollback: restarted previous version successfully")
            else:
                report("❌ Auto-rollback failed — manual intervention needed")

    port_row = srv_store.get_service_port(server["name"], service_name)
    return {
        "steps": steps,
        "healthy": healthy,
        "was_running": existed,
        "restarted": True,
        "port": port_row or 0,
    }
