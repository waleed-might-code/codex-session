from storage.base import *
from utils.crypto import encrypt, decrypt

TABLE_CF = "cf_config"
CF_SCHEMA = {
    "id": str, "token_enc": str, "account_id": str,
    "verified": str, "created_at": str, "updated_at": str,
}

TABLE_ZONES = "cf_zones"
ZONE_SCHEMA = {
    "id": str, "zone_id": str, "zone_name": str,
    "account_id": str, "created_at": str,
}

TABLE_TUNNELS = "cf_tunnels"
TUNNEL_SCHEMA = {
    "id": str, "tunnel_id": str, "tunnel_name": str,
    "server_name": str, "zone_id": str, "subdomain": str,
    "created_at": str, "updated_at": str, "status": str,
}

TABLE_PAGES = "cf_pages"
PAGES_SCHEMA = {
    "id": str, "project_name": str, "pages_project": str,
    "zone_id": str, "custom_domain": str, "url": str,
    "created_at": str, "updated_at": str,
}

TABLE_HOSTNAMES = "cf_hostnames"
HOSTNAME_SCHEMA = {
    "id": str,           # "{tunnel_id}:{subdomain}"
    "tunnel_id": str,
    "tunnel_name": str,
    "server_name": str,
    "zone_id": str,
    "zone_name": str,
    "subdomain": str,
    "hostname": str,     # full hostname e.g. "api.example.com"
    "service_name": str, # internal service name
    "port": str,         # local port the service runs on
    "service_url": str,  # e.g. "http://localhost:5025"
    "created_at": str,
    "updated_at": str,
}


def save_token(token: str, account_id: str):
    upsert(TABLE_CF, CF_SCHEMA, "id", "singleton", {
        "id": "singleton", "token_enc": encrypt(token),
        "account_id": account_id, "verified": "true",
        "created_at": now(), "updated_at": now(),
    })


def get_config() -> dict | None:
    return find_one(TABLE_CF, CF_SCHEMA, "id", "singleton")


def get_token() -> str | None:
    cfg = get_config()
    return decrypt(cfg["token_enc"]) if cfg and cfg.get("token_enc") else None


def get_account_id() -> str | None:
    cfg = get_config()
    return cfg.get("account_id") if cfg else None


def cache_zones(zones: list[dict]):
    import pandas as pd
    rows = [{"id": z["id"], "zone_id": z["id"], "zone_name": z["name"],
             "account_id": z.get("account", {}).get("id", ""), "created_at": now()} for z in zones]
    df = pd.DataFrame(rows, columns=list(ZONE_SCHEMA.keys()))
    save(TABLE_ZONES, df)


def list_zones() -> list[dict]:
    return find_all(TABLE_ZONES, ZONE_SCHEMA)


def save_tunnel(tunnel_id: str, tunnel_name: str, server_name: str,
                zone_id: str = "", subdomain: str = "") -> dict:
    rec = {
        "id": tunnel_id, "tunnel_id": tunnel_id, "tunnel_name": tunnel_name,
        "server_name": server_name, "zone_id": zone_id, "subdomain": subdomain,
        "created_at": now(), "updated_at": now(), "status": "active",
    }
    upsert(TABLE_TUNNELS, TUNNEL_SCHEMA, "tunnel_id", tunnel_id, rec)
    return rec


def get_tunnel_for_server(server_name: str) -> dict | None:
    return find_one(TABLE_TUNNELS, TUNNEL_SCHEMA, "server_name", server_name)


def list_tunnels() -> list[dict]:
    return find_all(TABLE_TUNNELS, TUNNEL_SCHEMA)


def save_pages(project_name: str, pages_project: str, url: str,
               zone_id: str = "", custom_domain: str = ""):
    upsert(TABLE_PAGES, PAGES_SCHEMA, "project_name", project_name, {
        "id": new_id(), "project_name": project_name, "pages_project": pages_project,
        "zone_id": zone_id, "custom_domain": custom_domain, "url": url,
        "created_at": now(), "updated_at": now(),
    })


def get_pages(project_name: str) -> dict | None:
    return find_one(TABLE_PAGES, PAGES_SCHEMA, "project_name", project_name)


def save_hostname(tunnel_id: str, tunnel_name: str, server_name: str,
                  zone_id: str, zone_name: str, subdomain: str,
                  service_name: str, port: int, service_url: str) -> dict:
    hostname = f"{subdomain}.{zone_name}"
    rec = {
        "id": f"{tunnel_id}:{subdomain}",
        "tunnel_id": tunnel_id,
        "tunnel_name": tunnel_name,
        "server_name": server_name,
        "zone_id": zone_id,
        "zone_name": zone_name,
        "subdomain": subdomain,
        "hostname": hostname,
        "service_name": service_name,
        "port": str(port),
        "service_url": service_url,
        "created_at": now(),
        "updated_at": now(),
    }
    upsert(TABLE_HOSTNAMES, HOSTNAME_SCHEMA, "id", rec["id"], rec)
    return rec


def get_hostname(tunnel_id: str, subdomain: str) -> dict | None:
    return find_one(TABLE_HOSTNAMES, HOSTNAME_SCHEMA, "id", f"{tunnel_id}:{subdomain}")


def list_hostnames_for_tunnel(tunnel_id: str) -> list[dict]:
    return [r for r in find_all(TABLE_HOSTNAMES, HOSTNAME_SCHEMA)
            if r["tunnel_id"] == tunnel_id]


def list_all_hostnames() -> list[dict]:
    return find_all(TABLE_HOSTNAMES, HOSTNAME_SCHEMA)


def hostname_in_use(subdomain: str, zone_name: str) -> dict | None:
    """Check if a subdomain.zone_name is already registered. Returns the record or None."""
    full = f"{subdomain}.{zone_name}"
    for r in find_all(TABLE_HOSTNAMES, HOSTNAME_SCHEMA):
        if r.get("hostname") == full:
            return r
    return None


def delete_hostname(tunnel_id: str, subdomain: str):
    delete_where(TABLE_HOSTNAMES, HOSTNAME_SCHEMA, "id", f"{tunnel_id}:{subdomain}")


def list_domain_map() -> list[dict]:
    """Return all hostname→service→port mappings from the hostname registry."""
    result = []
    for h in list_all_hostnames():
        result.append({
            "hostname": h.get("hostname", ""),
            "service": h.get("service_name", h.get("subdomain", "")),
            "server": h.get("server_name", ""),
            "port": int(h["port"]) if h.get("port") else None,
            "tunnel_id": h.get("tunnel_id", ""),
            "tunnel_status": "active",
            "service_url": h.get("service_url", ""),
        })
    return result
