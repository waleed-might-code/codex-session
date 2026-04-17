"""
SSH utilities: connectivity test, port scanning, bootstrap hardening.
"""
import io
import socket
import paramiko
from storage import decrypt_password, get_service_port, save_service_port

PORT_START = 5022  # start above 5021 per rules


def _client(host: dict, username_override: str = None) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    username = username_override or host["username"]
    hostname = host["host"]
    password = decrypt_password(host)
    ssh_key_str = host.get("ssh_key")

    if ssh_key_str:
        from storage import _decrypt
        key_data = _decrypt(ssh_key_str) if ssh_key_str.startswith("gAAAA") else ssh_key_str
        pkey = paramiko.RSAKey.from_private_key(io.StringIO(key_data))
        ssh.connect(hostname, username=username, pkey=pkey, timeout=10)
    else:
        ssh.connect(hostname, username=username, password=password, timeout=10)

    return ssh


def test_connection(host: dict) -> dict:
    """Returns {ok: bool, message: str, latency_ms: int}"""
    import time
    try:
        t0 = time.time()
        ssh = _client(host)
        _, stdout, _ = ssh.exec_command("uname -a")
        uname = stdout.read().decode().strip()
        ssh.close()
        ms = int((time.time() - t0) * 1000)
        return {"ok": True, "message": f"Connected in {ms}ms\n`{uname}`", "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "message": str(e), "latency_ms": -1}


def find_free_port(host: dict, service_name: str) -> int:
    """Scan remote host for a free port starting at PORT_START. Reuses persisted port if available."""
    existing = get_service_port(service_name, host["id"])
    if existing:
        return existing

    ssh = _client(host)
    port = PORT_START
    while True:
        _, stdout, _ = ssh.exec_command(f"ss -tlnp | grep :{port} | wc -l")
        count = int(stdout.read().decode().strip())
        if count == 0:
            break
        port += 1
    ssh.close()
    save_service_port(service_name, host["id"], port)
    return port


def bootstrap_host(host: dict) -> dict:
    """
    First-time hardening:
    1. Creates a 'deploy' user
    2. Generates an SSH keypair on the local side
    3. Installs the public key on the remote
    4. Returns the private key string for storage
    """
    try:
        ssh = _client(host)

        # Generate keypair
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend

        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=4096, backend=default_backend()
        )
        private_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        ).decode()
        public_openssh = private_key.public_key().public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH,
        ).decode()

        # Create deploy user and install key
        cmds = [
            "id deploy || useradd -m -s /bin/bash deploy",
            "mkdir -p /home/deploy/.ssh && chmod 700 /home/deploy/.ssh",
            f'echo "{public_openssh}" >> /home/deploy/.ssh/authorized_keys',
            "chmod 600 /home/deploy/.ssh/authorized_keys",
            "chown -R deploy:deploy /home/deploy/.ssh",
            "usermod -aG sudo deploy",
            "echo 'deploy ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deploy",
        ]
        for cmd in cmds:
            _, _, stderr = ssh.exec_command(cmd)
            err = stderr.read().decode().strip()
            if err and "already exists" not in err:
                pass  # non-fatal

        ssh.close()

        # Verify key auth works
        test_host = dict(host)
        test_host["username"] = "deploy"
        test_host["password"] = None
        test_host["ssh_key"] = private_pem
        result = test_connection(test_host)

        if result["ok"]:
            return {"ok": True, "private_key": private_pem, "message": "Deploy user created and key auth verified."}
        else:
            return {"ok": False, "private_key": private_pem, "message": f"User created but key auth check failed: {result['message']}"}

    except Exception as e:
        return {"ok": False, "private_key": None, "message": str(e)}


def run_command(host: dict, command: str, username_override: str = None) -> tuple[str, str, int]:
    """Run a command on the host, returns (stdout, stderr, exit_code)."""
    ssh = _client(host, username_override)
    _, stdout, stderr = ssh.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    ssh.close()
    return out, err, exit_code


def upload_file(host: dict, local_path: str, remote_path: str):
    """Upload a file via SFTP."""
    ssh = _client(host)
    sftp = ssh.open_sftp()
    sftp.put(local_path, remote_path)
    sftp.close()
    ssh.close()
