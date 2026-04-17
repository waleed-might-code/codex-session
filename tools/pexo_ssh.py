#!/usr/bin/env python3
"""
pexo-ssh: SSH CLI for Claude to use inside the agent bash tool.
Usage:
  pexo-ssh list                                    — list configured servers
  pexo-ssh <server> exec "<command>"               — run command on server
  pexo-ssh <server> logs <service> [--lines N]     — tail service logs
  pexo-ssh <server> deploy <service>               — deploy/restart a systemd service
      [--start-cmd "venv/bin/python app.py"]
      [--repo https://github.com/...]
      [--env KEY=VALUE ...]
  pexo-ssh <server> upload <local_path> <remote_path>  — upload a file
"""
import sys
import os

# Add projectexo root to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.servers as srv_store
import layers.ssh_layer as ssh


def get_server(name: str) -> dict:
    servers = {s["name"]: s for s in srv_store.list_all()}
    if not servers:
        print("ERROR: No SSH servers configured. Use /server add first.")
        sys.exit(1)
    if name not in servers:
        # Try first server if only one
        if len(servers) == 1:
            return list(servers.values())[0]
        print(f"ERROR: Server '{name}' not found. Available: {', '.join(servers)}")
        sys.exit(1)
    return servers[name]


def cmd_list():
    servers = srv_store.list_all()
    if not servers:
        print("No SSH servers configured.")
        return
    for s in servers:
        auth = "key" if s.get("auth_type") == "key" else "password"
        print(f"  {s['name']}: {s['username']}@{s['host']} (auth: {auth})")


def cmd_exec(server_name: str, command: str):
    server = get_server(server_name)
    out, err, code = ssh.run(server, command)
    if out:
        print(out)
    if err:
        print(f"[stderr] {err}", file=sys.stderr)
    sys.exit(code)


def cmd_logs(server_name: str, service: str, lines: int = 50):
    server = get_server(server_name)
    output = ssh.get_logs(server, service, lines=lines)
    print(output)


def cmd_deploy(server_name: str, service: str, args: list):
    server = get_server(server_name)
    start_cmd = None
    repo_url = None
    env_vars = {}

    i = 0
    while i < len(args):
        if args[i] == "--start-cmd" and i + 1 < len(args):
            start_cmd = args[i + 1]; i += 2
        elif args[i] == "--repo" and i + 1 < len(args):
            repo_url = args[i + 1]; i += 2
        elif args[i] == "--env" and i + 1 < len(args):
            kv = args[i + 1]
            k, _, v = kv.partition("=")
            env_vars[k] = v; i += 2
        else:
            i += 1

    result = ssh.deploy_service(
        server, service,
        repo_url=repo_url,
        start_cmd=start_cmd,
        env_vars=env_vars or None,
    )
    for step in result["steps"]:
        print(step)
    print(f"\nService port: {result['port']}")
    print(f"Deploy dir:   {result['deploy_dir']}")
    print(f"Status:       {'✅ active' if result['healthy'] else '❌ not active'}")


def cmd_upload(server_name: str, local_path: str, remote_path: str):
    server = get_server(server_name)
    content = open(local_path, errors="replace").read()
    ssh.upload_string(server, content, remote_path)
    print(f"Uploaded {local_path} → {remote_path}")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    if args[0] == "list":
        cmd_list()
    elif len(args) >= 3 and args[1] == "exec":
        cmd_exec(args[0], " ".join(args[2:]))
    elif len(args) >= 3 and args[1] == "logs":
        lines = 50
        service = args[2]
        if "--lines" in args:
            idx = args.index("--lines")
            lines = int(args[idx + 1])
        cmd_logs(args[0], service, lines)
    elif len(args) >= 3 and args[1] == "deploy":
        cmd_deploy(args[0], args[2], args[3:])
    elif len(args) >= 4 and args[1] == "upload":
        cmd_upload(args[0], args[2], args[3])
    else:
        print(f"Unknown command: {' '.join(args)}\n{__doc__}")
        sys.exit(1)


if __name__ == "__main__":
    main()
