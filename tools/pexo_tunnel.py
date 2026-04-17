#!/usr/bin/env python3
"""
pexo-tunnel: Cloudflare Tunnel CLI for Claude.
Reads its public domain and zone from environment variables.

Usage:
  pexo-tunnel expose <service-name> <local-port>   — create tunnel, DNS, install on server
  pexo-tunnel list                                  — list all tunnels
  pexo-tunnel status <service-name>                 — check tunnel + service status
  pexo-tunnel delete <service-name>                 — remove tunnel, DNS, systemd service
  pexo-tunnel logs <service-name>                   — tail tunnel service logs
"""
import sys, os, json, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import httpx
import storage.cloudflare as cf_store
import storage.servers as srv_store
import layers.ssh_layer as ssh_layer

DOMAIN = os.getenv("PEXO_CF_DOMAIN", "")
ZONE_ID = os.getenv("PEXO_CF_ZONE_ID", "")
CF_API = "https://api.cloudflare.com/client/v4"


def headers():
    return {
        "Authorization": f"Bearer {cf_store.get_token()}",
        "Content-Type": "application/json",
    }

def get_server():
    servers = srv_store.list_all()
    if not servers:
        print("ERROR: No SSH server configured.")
        sys.exit(1)
    return servers[0]

def api(method, path, data=None, params=None):
    r = httpx.request(method, f"{CF_API}{path}", headers=headers(), json=data, params=params, timeout=20)
    return r.status_code, r.json()

def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def require_cf_config():
    if not DOMAIN or not ZONE_ID:
        die("Set PEXO_CF_DOMAIN and PEXO_CF_ZONE_ID before using pexo-tunnel.")


def expose(service_name, port):
    require_cf_config()
    account_id = cf_store.get_account_id()
    server = get_server()
    hostname = f"{service_name}.{DOMAIN}"
    tunnel_name = f"pexo-{service_name}"

    print(f"🔧 Setting up tunnel: {hostname} → localhost:{port}")

    # Check for port conflicts
    existing_svc = srv_store.port_in_use(server["name"], port)
    if existing_svc and existing_svc != service_name:
        print(f"⚠️  WARNING: Port {port} is already allocated to service '{existing_svc}'!")
        print(f"   This will create a conflict. Consider using a different port.")
        print(f"   Existing services on this server:")
        for svc in srv_store.list_services_for_server(server["name"]):
            print(f"     port {svc['port']} → {svc['service_name']}")

    # Check for domain conflicts
    domain_map = cf_store.list_domain_map()
    for dm in domain_map:
        if dm["hostname"] == hostname and dm.get("port") and dm["port"] != port:
            print(f"⚠️  WARNING: {hostname} is currently mapped to port {dm['port']}!")
            print(f"   Updating to port {port}.")

    # 1. Check if tunnel already exists
    status, data = api("GET", f"/accounts/{account_id}/cfd_tunnel", params={"name": tunnel_name, "is_deleted": "false"})
    existing = next((t for t in (data.get("result") or []) if t["name"] == tunnel_name), None)

    if existing:
        tunnel_id = existing["id"]
        print(f"  ✅ Reusing existing tunnel: {tunnel_id}")
    else:
        # Create tunnel
        import secrets
        tunnel_secret = secrets.token_hex(32)
        status, data = api("POST", f"/accounts/{account_id}/cfd_tunnel", {
            "name": tunnel_name,
            "tunnel_secret": tunnel_secret,
        })
        if not data.get("success"):
            die(f"Failed to create tunnel: {data.get('errors')}")
        tunnel_id = data["result"]["id"]
        print(f"  ✅ Tunnel created: {tunnel_id}")

    # 2. Get tunnel token
    status, data = api("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token")
    if not data.get("success"):
        die(f"Failed to get tunnel token: {data.get('errors')}")
    tunnel_token = data["result"]

    # 3. Configure ingress
    ingress_config = {
        "config": {
            "ingress": [
                {"hostname": hostname, "service": f"http://localhost:{port}"},
                {"service": "http_status:404"},
            ]
        }
    }
    status, data = api("PUT", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations", ingress_config)
    if not data.get("success"):
        print(f"  ⚠️  Ingress config warning: {data.get('errors')}")
    else:
        print(f"  ✅ Ingress configured → localhost:{port}")

    # 4. Create/update DNS record
    status, existing_dns = api("GET", f"/zones/{ZONE_ID}/dns_records", params={"name": hostname})
    dns_records = existing_dns.get("result") or []
    dns_payload = {
        "type": "CNAME",
        "name": hostname,
        "content": f"{tunnel_id}.cfargotunnel.com",
        "proxied": True,
        "ttl": 1,
    }
    if dns_records:
        rec_id = dns_records[0]["id"]
        api("PUT", f"/zones/{ZONE_ID}/dns_records/{rec_id}", dns_payload)
        print(f"  ✅ DNS updated: {hostname}")
    else:
        api("POST", f"/zones/{ZONE_ID}/dns_records", dns_payload)
        print(f"  ✅ DNS created: {hostname}")

    # 5. Install cloudflared on server
    out, err, code = ssh_layer.run(server,
        "which cloudflared || ("
        "curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
        "-o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared && echo installed"
        ")"
    )
    print(f"  ✅ cloudflared ready on server")

    # 6. Write per-service systemd unit
    svc_name = f"cf-tunnel-{service_name}"
    unit = f"""[Unit]
Description=Cloudflare Tunnel for {service_name}
After=network.target {service_name}.service
Wants={service_name}.service

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate run --token {tunnel_token}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    ssh_layer.upload_string(server, unit, f"/etc/systemd/system/{svc_name}.service")
    out, err, code = ssh_layer.run(server,
        f"systemctl daemon-reload && systemctl enable {svc_name} && systemctl restart {svc_name}"
    )
    print(f"  {'✅' if code == 0 else '❌'} Tunnel service {svc_name}: {'started' if code == 0 else err[:80]}")

    # 7. Wait and verify
    time.sleep(4)
    out, err, _ = ssh_layer.run(server, f"systemctl is-active {svc_name}")
    active = out.strip() == "active"
    print(f"  {'✅' if active else '❌'} Service status: {out.strip()}")

    print(f"\n✅ Tunnel live!")
    print(f"URL=https://{hostname}")
    print(f"PUBLIC_URL=https://{hostname}")
    cf_store.save_tunnel(tunnel_id, tunnel_name, server["name"], ZONE_ID, service_name)


def list_tunnels():
    require_cf_config()
    account_id = cf_store.get_account_id()
    status, data = api("GET", f"/accounts/{account_id}/cfd_tunnel", params={"is_deleted": "false"})
    tunnels = data.get("result") or []
    pexo = [t for t in tunnels if t["name"].startswith("pexo-")]
    if not pexo:
        print("No pexo tunnels found.")
        return

    server = get_server()
    print(f"{'Service':30s}   {'URL':40s}   {'Port':8s}  {'Status':12s}  ID")
    print("-" * 100)
    for t in pexo:
        service = t["name"].replace("pexo-", "")
        port = srv_store.get_service_port(server["name"], service)
        port_str = str(port) if port else "???"
        print(f"  {service:30s} → https://{service}.{DOMAIN}  port:{port_str:5s}  [{t['status']}]  id:{t['id'][:8]}")


def status(service_name):
    require_cf_config()
    account_id = cf_store.get_account_id()
    tunnel_name = f"pexo-{service_name}"
    status_code, data = api("GET", f"/accounts/{account_id}/cfd_tunnel", params={"name": tunnel_name})
    tunnel = next((t for t in (data.get("result") or []) if t["name"] == tunnel_name), None)
    if not tunnel:
        print(f"No tunnel found for {service_name}")
        return
    print(f"Tunnel:  {tunnel['id']}")
    print(f"Status:  {tunnel['status']}")
    print(f"URL:     https://{service_name}.{DOMAIN}")

    server = get_server()
    svc_name = f"cf-tunnel-{service_name}"
    out, _, _ = ssh_layer.run(server, f"systemctl is-active {svc_name}")
    print(f"Service: {out.strip()}")


def delete(service_name):
    require_cf_config()
    account_id = cf_store.get_account_id()
    tunnel_name = f"pexo-{service_name}"
    server = get_server()
    hostname = f"{service_name}.{DOMAIN}"
    svc_name = f"cf-tunnel-{service_name}"

    # Stop service
    ssh_layer.run(server, f"systemctl stop {svc_name} && systemctl disable {svc_name} 2>/dev/null || true")
    print(f"✅ Service stopped")

    # Delete DNS
    status_code, data = api("GET", f"/zones/{ZONE_ID}/dns_records", params={"name": hostname})
    for rec in (data.get("result") or []):
        api("DELETE", f"/zones/{ZONE_ID}/dns_records/{rec['id']}")
    print(f"✅ DNS removed")

    # Delete tunnel
    status_code, data = api("GET", f"/accounts/{account_id}/cfd_tunnel", params={"name": tunnel_name})
    tunnel = next((t for t in (data.get("result") or []) if t["name"] == tunnel_name), None)
    if tunnel:
        api("DELETE", f"/accounts/{account_id}/cfd_tunnel/{tunnel['id']}")
        print(f"✅ Tunnel deleted")


def logs(service_name):
    server = get_server()
    svc_name = f"cf-tunnel-{service_name}"
    out, err, _ = ssh_layer.run(server, f"journalctl -u {svc_name} --no-pager -n 30")
    print(out or err)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); sys.exit(0)

    cmd = args[0]
    if cmd == "expose" and len(args) >= 3:
        expose(args[1], int(args[2]))
    elif cmd == "list":
        list_tunnels()
    elif cmd == "status" and len(args) >= 2:
        status(args[1])
    elif cmd == "delete" and len(args) >= 2:
        delete(args[1])
    elif cmd == "logs" and len(args) >= 2:
        logs(args[1])
    else:
        print(__doc__); sys.exit(1)

if __name__ == "__main__":
    main()
