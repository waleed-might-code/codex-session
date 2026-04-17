from storage.base import *
from utils.crypto import encrypt, decrypt

TABLE = "servers"
SCHEMA = {
    "id": str, "name": str, "host": str, "username": str,
    "auth_type": str,   # password | key
    "password_enc": str, "key_enc": str,
    "is_default": str, "status": str,
    "created_at": str, "updated_at": str,
}

TABLE_DEPLOYS = "deploys"
DEPLOY_SCHEMA = {
    "id": str, "project_name": str, "server_name": str,
    "service_name": str, "port": str, "deploy_type": str,
    "status": str, "commit": str, "url": str,
    "created_at": str, "updated_at": str,
}

TABLE_SERVICES = "services"
SERVICE_SCHEMA = {
    "id": str, "server_name": str, "service_name": str, "port": str, "updated_at": str,
}


def add(name: str, host: str, username: str, password: str = "", ssh_key: str = "", make_default: bool = False) -> dict:
    auth_type = "key" if ssh_key else "password"
    rec = {
        "id": new_id(), "name": name, "host": host, "username": username,
        "auth_type": auth_type,
        "password_enc": encrypt(password) if password else "",
        "key_enc": encrypt(ssh_key) if ssh_key else "",
        "is_default": "true" if make_default else "false",
        "status": "unknown", "created_at": now(), "updated_at": now(),
    }
    upsert(TABLE, SCHEMA, "name", name, rec)
    return rec


def get(name: str) -> dict | None:
    return find_one(TABLE, SCHEMA, "name", name)


def get_default() -> dict | None:
    rows = find_all(TABLE, SCHEMA)
    defaults = [r for r in rows if r["is_default"] == "true"]
    return defaults[0] if defaults else (rows[0] if rows else None)


def list_all() -> list[dict]:
    return find_all(TABLE, SCHEMA)


def set_default(name: str):
    df = load(TABLE, SCHEMA)
    df["is_default"] = df["name"].apply(lambda n: "true" if n == name else "false")
    save(TABLE, df)


def update_status(name: str, status: str):
    upsert(TABLE, SCHEMA, "name", name, {"status": status})


def update_key(name: str, username: str, ssh_key: str):
    upsert(TABLE, SCHEMA, "name", name, {
        "username": username, "auth_type": "key",
        "key_enc": encrypt(ssh_key), "password_enc": "",
    })


def get_password(server: dict) -> str:
    return decrypt(server["password_enc"]) if server.get("password_enc") else ""


def get_key(server: dict) -> str:
    return decrypt(server["key_enc"]) if server.get("key_enc") else ""


def remove(name: str):
    delete_where(TABLE, SCHEMA, "name", name)


# ── Service port tracking ─────────────────────────────────────────────────────

def get_service_port(server_name: str, service_name: str) -> int | None:
    row = None
    rows = find_all(TABLE_SERVICES, SERVICE_SCHEMA)
    for r in rows:
        if r["server_name"] == server_name and r["service_name"] == service_name:
            row = r
    return int(row["port"]) if row and row.get("port") else None


def save_service_port(server_name: str, service_name: str, port: int):
    key = f"{server_name}:{service_name}"
    upsert(TABLE_SERVICES, SERVICE_SCHEMA, "id", key, {
        "id": key, "server_name": server_name, "service_name": service_name,
        "port": str(port), "updated_at": now(),
    })


# ── Deploy history ────────────────────────────────────────────────────────────

def record_deploy(project_name: str, server_name: str, service_name: str, port: int,
                  deploy_type: str, status: str, url: str = "", commit: str = "") -> dict:
    rec = {
        "id": new_id(), "project_name": project_name, "server_name": server_name,
        "service_name": service_name, "port": str(port), "deploy_type": deploy_type,
        "status": status, "commit": commit, "url": url,
        "created_at": now(), "updated_at": now(),
    }
    upsert(TABLE_DEPLOYS, DEPLOY_SCHEMA, "id", rec["id"], rec)
    return rec


def list_deploys(project_name: str = None) -> list[dict]:
    if project_name:
        return find_all(TABLE_DEPLOYS, DEPLOY_SCHEMA, "project_name", project_name)
    return find_all(TABLE_DEPLOYS, DEPLOY_SCHEMA)


def list_all_ports(server_name: str = None) -> list[dict]:
    """List all allocated ports, optionally filtered by server."""
    rows = find_all(TABLE_SERVICES, SERVICE_SCHEMA)
    if server_name:
        rows = [r for r in rows if r["server_name"] == server_name]
    return rows


def port_in_use(server_name: str, port: int) -> str | None:
    """Check if a port is already allocated on a server. Returns service_name if in use."""
    for r in find_all(TABLE_SERVICES, SERVICE_SCHEMA):
        if r["server_name"] == server_name and r.get("port") == str(port):
            return r["service_name"]
    return None


def list_services_for_server(server_name: str) -> list[dict]:
    """List all services and their ports for a server."""
    return [r for r in find_all(TABLE_SERVICES, SERVICE_SCHEMA) if r["server_name"] == server_name]


def allocate_port(server_name: str, service_name: str, start: int = 5100) -> int:
    """
    Find and reserve the next available port on a server.
    Checks both the local registry and any existing allocation for this service.
    Ports 1-1024 and 5000 are avoided.
    Returns the allocated port (already saved to registry).
    """
    # If service already has a port, return it
    existing = get_service_port(server_name, service_name)
    if existing:
        return existing

    # Collect all ports already in use on this server
    used = {int(r["port"]) for r in list_services_for_server(server_name) if r.get("port")}
    # Also avoid common system/conflict ports
    avoid = {22, 80, 443, 3306, 5432, 6379, 5000, 8080}
    used |= avoid

    port = max(start, 5100)
    while port in used or port > 65000:
        port += 1

    save_service_port(server_name, service_name, port)
    return port


def free_port(server_name: str, service_name: str):
    """Release a port allocation for a service."""
    delete_where(TABLE_SERVICES, SERVICE_SCHEMA, "id", f"{server_name}:{service_name}")


def seed_default(host: str, username: str, password: str):
    """Seed default server on first run if none exist."""
    if not find_all(TABLE, SCHEMA):
        add("default", host, username, password=password, make_default=True)
        print(f"[storage] Seeded default server: {host}")
