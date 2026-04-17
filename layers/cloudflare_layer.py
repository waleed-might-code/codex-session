"""
Cloudflare API layer.
Manages: zones, tunnels, Pages deployments, hostname binding.
Uses Cloudflare REST API directly via httpx.
"""
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
import httpx
import storage.cloudflare as cf_store

CF_API = "https://api.cloudflare.com/client/v4"


def _headers(token: str = None) -> dict:
    t = token or cf_store.get_token()
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


async def verify_token(token: str) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{CF_API}/user/tokens/verify", headers=_headers(token))
    data = r.json()
    return {"ok": data.get("success"), "data": data.get("result", {})}


async def get_account_id(token: str) -> str | None:
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{CF_API}/accounts", headers=_headers(token))
    data = r.json()
    if data.get("success") and data.get("result"):
        return data["result"][0]["id"]
    return None


async def list_zones() -> list[dict]:
    account_id = cf_store.get_account_id()
    params = {"account.id": account_id, "per_page": 50} if account_id else {"per_page": 50}
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{CF_API}/zones", headers=_headers(), params=params)
    zones = r.json().get("result", [])
    cf_store.cache_zones(zones)
    return zones


async def ensure_tunnel(server_name: str, tunnel_name: str = None) -> dict:
    """Create or reuse a Cloudflare Tunnel for a server."""
    existing = cf_store.get_tunnel_for_server(server_name)
    if existing and existing.get("tunnel_id"):
        return {"created": False, "tunnel": existing}

    name = tunnel_name or f"projectexo-{server_name}"
    account_id = cf_store.get_account_id()
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{CF_API}/accounts/{account_id}/cfd_tunnel",
            headers=_headers(),
            json={"name": name, "tunnel_secret": os.urandom(32).hex()},
        )
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Tunnel creation failed: {data.get('errors')}")

    tunnel = data["result"]
    saved = cf_store.save_tunnel(tunnel["id"], tunnel["name"], server_name)
    return {"created": True, "tunnel": saved, "token": tunnel.get("token", "")}


async def get_tunnel_token(tunnel_id: str) -> str:
    account_id = cf_store.get_account_id()
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{CF_API}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token",
            headers=_headers(),
        )
    return r.json().get("result", "")


async def attach_hostname(tunnel_id: str, zone_id: str, subdomain: str,
                          service_url: str, service_name: str = "") -> dict:
    """
    Bind a public hostname to the tunnel pointing at service_url.
    Preserves all existing hostname routes — does NOT overwrite them.
    Updates the route if subdomain already exists.
    """
    account_id = cf_store.get_account_id()

    # Get zone name
    async with httpx.AsyncClient(timeout=30) as c:
        rz = await c.get(f"{CF_API}/zones/{zone_id}", headers=_headers())
    zone_name = rz.json().get("result", {}).get("name", "")
    hostname = f"{subdomain}.{zone_name}" if subdomain else zone_name

    # GET current ingress config — we must preserve existing routes
    async with httpx.AsyncClient(timeout=30) as c:
        rc = await c.get(
            f"{CF_API}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            headers=_headers(),
        )
    existing_config = rc.json().get("result", {}).get("config", {})
    existing_ingress = existing_config.get("ingress", [])

    # Remove the catch-all 404 entry and any existing entry for this hostname
    routes = [r for r in existing_ingress
              if r.get("service") != "http_status:404"
              and r.get("hostname") != hostname]

    # Add/update this hostname route at the front
    routes.insert(0, {"hostname": hostname, "service": service_url})

    # Always end with catch-all
    routes.append({"service": "http_status:404"})

    config = {"config": {"ingress": routes}}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.put(
            f"{CF_API}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            headers=_headers(), json=config,
        )
    if not r.json().get("success"):
        raise RuntimeError(f"Hostname attach failed: {r.json().get('errors')}")

    # Create or update DNS CNAME record (check for existing first)
    cname_content = f"{tunnel_id}.cfargotunnel.com"
    async with httpx.AsyncClient(timeout=30) as c:
        existing_dns = await c.get(
            f"{CF_API}/zones/{zone_id}/dns_records",
            headers=_headers(),
            params={"type": "CNAME", "name": hostname},
        )
    existing_records = existing_dns.json().get("result", [])

    async with httpx.AsyncClient(timeout=30) as c:
        if existing_records:
            # Update existing record
            record_id = existing_records[0]["id"]
            await c.put(
                f"{CF_API}/zones/{zone_id}/dns_records/{record_id}",
                headers=_headers(),
                json={"type": "CNAME", "name": hostname, "content": cname_content,
                      "proxied": True, "ttl": 1},
            )
        else:
            # Create new record
            await c.post(
                f"{CF_API}/zones/{zone_id}/dns_records",
                headers=_headers(),
                json={"type": "CNAME", "name": hostname, "content": cname_content,
                      "proxied": True, "ttl": 1},
            )

    # Save to hostname registry
    tunnel_rec = cf_store.get_tunnel_for_server(
        next((t["server_name"] for t in cf_store.list_tunnels() if t["tunnel_id"] == tunnel_id), "")
    )
    server_name = tunnel_rec["server_name"] if tunnel_rec else ""
    tunnel_name = tunnel_rec["tunnel_name"] if tunnel_rec else ""

    # Extract port from service_url
    try:
        port = int(service_url.split(":")[-1])
    except Exception:
        port = 0

    cf_store.save_hostname(
        tunnel_id=tunnel_id,
        tunnel_name=tunnel_name,
        server_name=server_name,
        zone_id=zone_id,
        zone_name=zone_name,
        subdomain=subdomain,
        service_name=service_name or subdomain,
        port=port,
        service_url=service_url,
    )

    # Update tunnel record with zone/subdomain (last attached, for backwards compat)
    cf_store.save_tunnel(tunnel_id, tunnel_name, server_name, zone_id, subdomain)

    return {"hostname": hostname, "url": f"https://{hostname}"}


async def get_tunnel_ingress(tunnel_id: str) -> list[dict]:
    """Return the current ingress rules for a tunnel."""
    account_id = cf_store.get_account_id()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            f"{CF_API}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            headers=_headers(),
        )
    config = r.json().get("result", {}).get("config", {})
    return config.get("ingress", [])


async def deploy_pages(project_path: str, project_name: str, branch: str = "main") -> dict:
    """Deploy a static frontend to Cloudflare Pages via Wrangler CLI."""
    pages_name = project_name.lower().replace("_", "-").replace(" ", "-")

    # Check for wrangler
    wrangler = subprocess.run("which wrangler", shell=True, capture_output=True).stdout.strip()
    if not wrangler:
        subprocess.run("npm install -g wrangler --silent", shell=True)

    token = cf_store.get_token()
    account_id = cf_store.get_account_id()

    if not token:
        return {"ok": False, "url": "", "output": "Cloudflare token not configured — use /cloudflare connect first.", "pages_project": pages_name}
    if not account_id:
        return {"ok": False, "url": "", "output": "Cloudflare account ID missing — reconnect with /cloudflare connect.", "pages_project": pages_name}

    env = {**os.environ, "CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": account_id}

    # Determine build output directory — pick the one with actual HTML content
    p = Path(project_path)
    dist_dir = "."
    for candidate in ["dist", "build", "out", ".next", "public", "."]:
        cand = p / candidate
        if cand.exists() and (list(cand.rglob("*.html")) or list(cand.rglob("index.*"))):
            dist_dir = candidate
            break

    cmd = (
        f"wrangler pages deploy {dist_dir} "
        f"--project-name={pages_name} "
        f"--branch={branch} "
        f"--commit-dirty=true"
    )

    proc = await asyncio.create_subprocess_shell(
        cmd, cwd=project_path, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    output = (stdout + stderr).decode(errors="replace")

    # Extract URL from output
    url = ""
    for line in output.splitlines():
        if "pages.dev" in line or "workers.dev" in line:
            parts = line.split()
            for p in parts:
                if "pages.dev" in p or "workers.dev" in p:
                    url = p.strip()
                    break

    return {
        "ok": proc.returncode == 0,
        "url": url,
        "output": output[-2000:],
        "pages_project": pages_name,
    }


async def install_tunnel_on_server(server: dict, tunnel_token: str, service_port: int) -> dict:
    """Install cloudflared on the SSH server and start the tunnel as a systemd service."""
    from layers import ssh_layer

    steps = []

    # Install cloudflared
    out, err, code = await ssh_layer.run_async(server,
        "which cloudflared || "
        "(curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
        "-o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared)"
    )
    steps.append(f"{'✅' if code == 0 else '❌'} cloudflared installed")

    # Write systemd service
    unit = f"""[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate run --token {tunnel_token}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    ssh_layer.upload_string(server, unit, "/etc/systemd/system/cloudflared.service")

    out, err, code = await ssh_layer.run_async(server,
        "systemctl daemon-reload && systemctl enable cloudflared && systemctl restart cloudflared"
    )
    steps.append(f"{'✅' if code == 0 else '❌'} Tunnel service started")

    return {"ok": code == 0, "steps": steps}
