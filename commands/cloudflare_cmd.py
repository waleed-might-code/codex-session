import storage.cloudflare as cf_store
import storage.servers as srv_store
import layers.cloudflare_layer as cf_layer
from utils.discord_helpers import followup, opts


async def handle(sub: str, sub_opts: list, token: str, channel_id: str):
    o = opts(sub_opts)

    if sub == "connect":
        cf_token = o.get("token", "")
        if not cf_token:
            return await followup(token,
                "❌ `token` is required.\n\n"
                "Get a scoped API token from [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens) with:\n"
                "- Zone:Read, DNS:Edit, Cloudflare Tunnel:Edit, Pages:Edit"
            )
        await followup(token, "🔄 Verifying Cloudflare token...")
        result = await cf_layer.verify_token(cf_token)
        if not result["ok"]:
            return await followup(token, f"❌ Token verification failed: {result['data']}")

        account_id = await cf_layer.get_account_id(cf_token)
        cf_store.save_token(cf_token, account_id or "")
        await followup(token,
            f"✅ Cloudflare connected!\n"
            f"Account ID: `{account_id}`\n"
            f"Token stored encrypted. Use `/cloudflare domains` to list zones."
        )

    elif sub == "domains":
        if not cf_store.get_token():
            return await followup(token, "❌ Not connected. Use `/cloudflare connect` first.")
        await followup(token, "🔄 Fetching domains...")
        zones = await cf_layer.list_zones()
        if not zones:
            return await followup(token, "No zones/domains found in your account.")
        lines = ["**Your Cloudflare Domains:**"]
        for z in zones:
            lines.append(f"• `{z['name']}` — ID: `{z['id']}`")
        await followup(token, "\n".join(lines))

    elif sub == "tunnel":
        if not cf_store.get_token():
            return await followup(token, "❌ Not connected. Use `/cloudflare connect` first.")
        server_name = o.get("server", "")
        server = srv_store.get(server_name) if server_name else srv_store.get_default()
        if not server:
            return await followup(token, "❌ Server not found.")
        await followup(token, f"🔄 Ensuring tunnel for server **{server['name']}**...")
        result = await cf_layer.ensure_tunnel(server["name"])
        tunnel = result["tunnel"]
        created = result["created"]
        label = "🆕 Created" if created else "♻️ Reusing existing"
        await followup(token,
            f"✅ {label} tunnel for **{server['name']}**\n"
            f"Tunnel ID: `{tunnel['tunnel_id']}`\n"
            f"Tunnel Name: `{tunnel['tunnel_name']}`\n\n"
            f"Next: `/cloudflare hostname` to attach a public URL."
        )

    elif sub == "hostname":
        if not cf_store.get_token():
            return await followup(token, "❌ Not connected. Use `/cloudflare connect` first.")
        server_name = o.get("server", "")
        subdomain = o.get("subdomain", "")
        zone_name = o.get("zone", "")
        service_name = o.get("service", subdomain)  # service name defaults to subdomain
        port_override = o.get("port")

        if not subdomain:
            return await followup(token, "❌ `subdomain` is required.")

        server = srv_store.get(server_name) if server_name else srv_store.get_default()
        if not server:
            return await followup(token, "❌ Server not found.")

        tunnel = cf_store.get_tunnel_for_server(server["name"])
        if not tunnel:
            return await followup(token, "❌ No tunnel found. Run `/cloudflare tunnel` first.")

        # Find zone
        zones = cf_store.list_zones()
        zone = next((z for z in zones if z["zone_name"] == zone_name or z["zone_id"] == zone_name), None)
        if not zone and zones:
            zone = zones[0]
        if not zone:
            return await followup(token, "❌ Zone not found. Run `/cloudflare domains` first.")

        # Conflict check: is this hostname already mapped?
        conflict = cf_store.hostname_in_use(subdomain, zone["zone_name"])
        if conflict and not port_override:
            existing_service = conflict.get("service_name", "?")
            existing_port = conflict.get("port", "?")
            existing_url = f"https://{conflict['hostname']}"
            return await followup(token,
                f"⚠️ `{subdomain}.{zone['zone_name']}` is already mapped to service "
                f"**{existing_service}** on port **{existing_port}**.\n"
                f"Current URL: {existing_url}\n\n"
                f"If you want to remap it to a different service, specify the `port` explicitly."
            )

        # Find port: use port_override, or look up service registry, or fail clearly
        if port_override:
            port = int(port_override)
        else:
            port = srv_store.get_service_port(server["name"], service_name)
            if not port:
                # Show what's available
                services = srv_store.list_services_for_server(server["name"])
                if services:
                    svc_list = "\n".join(f"  • `{s['service_name']}` → port {s['port']}" for s in services)
                    return await followup(token,
                        f"❌ No port registered for service `{service_name}` on server `{server['name']}`.\n\n"
                        f"**Registered services:**\n{svc_list}\n\n"
                        f"Use the `service` option to specify the service name, or `port` to set the port directly."
                    )
                else:
                    return await followup(token,
                        f"❌ No services registered on server `{server['name']}` yet.\n"
                        f"Deploy a service first, then run this command."
                    )

        service_url = f"http://localhost:{port}"
        hostname_full = f"{subdomain}.{zone['zone_name']}"

        await followup(token,
            f"🔄 Attaching `{hostname_full}` → tunnel → `{service_url}` (service: {service_name})..."
        )

        try:
            result = await cf_layer.attach_hostname(
                tunnel["tunnel_id"], zone["zone_id"], subdomain, service_url,
                service_name=service_name,
            )
            # Save port to registry if not already there
            srv_store.save_service_port(server["name"], service_name, port)
            await followup(token,
                f"✅ Hostname attached!\n"
                f"🔗 **Public URL:** {result['url']}\n"
                f"Service: `{service_name}` on port `{port}`\n"
                f"Propagation takes ~30 seconds."
            )
        except Exception as e:
            await followup(token, f"❌ Failed: {e}")

    elif sub == "links":
        tunnels = cf_store.list_tunnels()
        if not tunnels:
            return await followup(token, "No active tunnels/links found.")
        lines = ["**Active Cloudflare Links:**"]
        for t in tunnels:
            if t.get("subdomain") and t.get("zone_id"):
                zones = cf_store.list_zones()
                zone = next((z for z in zones if z["zone_id"] == t["zone_id"]), {})
                zone_name = zone.get("zone_name", t["zone_id"])
                url = f"https://{t['subdomain']}.{zone_name}"
                lines.append(f"• **{t['server_name']}** → 🔗 {url}")
            else:
                lines.append(f"• **{t['server_name']}** — tunnel `{t['tunnel_id']}` (no hostname yet)")
        await followup(token, "\n".join(lines))

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
