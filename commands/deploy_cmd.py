import asyncio
import storage.servers as srv_store
import storage.projects as proj_store
import storage.cloudflare as cf_store
import layers.ssh_layer as ssh
import layers.cloudflare_layer as cf_layer
from utils.discord_helpers import followup, followup_chunks, opts
from utils.security import truncate


async def handle(sub: str, sub_opts: list, token: str, channel_id: str):
    o = opts(sub_opts)

    if sub == "api":
        server_name = o.get("server", "")
        server = srv_store.get(server_name) if server_name else srv_store.get_default()
        if not server:
            return await followup(token, "❌ No server configured. Use `/server add` first.")

        proj = proj_store.get_by_channel(channel_id)
        project_name = o.get("project", proj["name"] if proj else "api")
        service = o.get("service", project_name.lower().replace(" ", "-"))
        repo = o.get("repo", "")
        branch = o.get("branch", "main")
        start_cmd = o.get("start_cmd", "")

        await followup(token, f"🚀 Deploying `{service}` → `{server['host']}`...")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: ssh.deploy_service(
            server=server, service_name=service,
            repo_url=repo or None, branch=branch,
            project_path=proj["path"] if proj else None,
            start_cmd=start_cmd or None,
        ))

        steps_text = "\n".join(result["steps"])
        port = result["port"]
        deploy_url = f"http://{server['host']}:{port}"

        srv_store.record_deploy(
            project_name=project_name, server_name=server["name"],
            service_name=service, port=port, deploy_type="api",
            status="healthy" if result["healthy"] else "unhealthy",
            url=deploy_url,
        )

        await followup(token,
            f"{'✅ Deploy complete' if result['healthy'] else '⚠️ Deploy finished (check health)'}:\n"
            f"{steps_text}\n"
            f"🔒 Deployed on `{server['host']}` — private port `{port}`\n"
            f"Use `/cloudflare tunnel` + `/cloudflare hostname` to expose it publicly."
        )

    elif sub == "web":
        proj = proj_store.get_by_channel(channel_id)
        project_name = o.get("project", proj["name"] if proj else "web")
        target = o.get("target", "pages")
        branch = o.get("branch", "main")

        if not proj:
            return await followup(token, "❌ No active project. Use `/project use` first.")
        if not cf_store.get_token():
            return await followup(token, "❌ Cloudflare not connected. Use `/cloudflare connect` first.")

        await followup(token, f"🌐 Deploying **{proj['name']}** frontend to Cloudflare Pages...")

        result = await cf_layer.deploy_pages(proj["path"], project_name, branch)
        cf_store.save_pages(project_name, result["pages_project"], result.get("url", ""))

        if result["ok"]:
            await followup(token,
                f"✅ Frontend deployed!\n"
                f"🔗 **URL:** {result.get('url', '(check Cloudflare dashboard)')}\n"
                f"Project: `{result['pages_project']}`"
            )
        else:
            await followup_chunks(token, f"❌ Deploy failed:\n{result['output']}")

    elif sub == "full":
        proj = proj_store.get_by_channel(channel_id)
        server_name = o.get("server", "")
        server = srv_store.get(server_name) if server_name else srv_store.get_default()
        frontend_target = o.get("frontend_target", "pages")

        if not proj:
            return await followup(token, "❌ No active project. Use `/project use` first.")
        if not server:
            return await followup(token, "❌ No server configured.")

        await followup(token, f"🚀 Full-stack deploy: **{proj['name']}** → `{server['host']}`\n_This may take a few minutes..._")

        # 1. Deploy backend
        await followup(token, "**[1/4]** Deploying backend...")
        service = proj["name"].lower().replace(" ", "-") + "-api"
        loop = asyncio.get_event_loop()
        backend = await loop.run_in_executor(None, lambda: ssh.deploy_service(
            server=server, service_name=service,
        ))
        await followup(token, f"Backend: {'✅' if backend['healthy'] else '⚠️'} port `{backend['port']}`")

        # 2. Ensure tunnel
        if cf_store.get_token():
            await followup(token, "**[2/4]** Ensuring Cloudflare tunnel...")
            try:
                tunnel_result = await cf_layer.ensure_tunnel(server["name"])
                t = tunnel_result["tunnel"]
                await followup(token, f"Tunnel: ✅ `{t['tunnel_name']}`")
            except Exception as e:
                await followup(token, f"Tunnel: ⚠️ {e}")
        else:
            await followup(token, "**[2/4]** Skipping tunnel (Cloudflare not connected)")

        # 3. Deploy frontend
        if cf_store.get_token():
            await followup(token, "**[3/4]** Deploying frontend...")
            try:
                pages = await cf_layer.deploy_pages(proj["path"], proj["name"])
                frontend_url = pages.get("url", "(check dashboard)")
                await followup(token, f"Frontend: {'✅' if pages['ok'] else '⚠️'} {frontend_url}")
            except Exception as e:
                await followup(token, f"Frontend: ⚠️ {e}")
                frontend_url = ""
        else:
            frontend_url = ""
            await followup(token, "**[3/4]** Skipping frontend (Cloudflare not connected)")

        # 4. Summary
        backend_url = f"http://{server['host']}:{backend['port']}"
        srv_store.record_deploy(
            project_name=proj["name"], server_name=server["name"],
            service_name=service, port=backend["port"], deploy_type="full",
            status="healthy" if backend["healthy"] else "partial",
            url=frontend_url or backend_url,
        )
        await followup(token,
            f"**[4/4] ✅ Full deploy complete!**\n"
            f"🔧 Backend: `{backend_url}` (make public with `/cloudflare hostname`)\n"
            f"🌐 Frontend: {frontend_url or '(not deployed)'}"
        )

    elif sub == "status":
        server_name = o.get("server", "")
        server = srv_store.get(server_name) if server_name else srv_store.get_default()
        if not server:
            return await followup(token, "❌ No server configured.")

        await followup(token, f"🔍 Checking services on `{server['host']}`...")
        out, err, _ = await ssh.run_async(server,
            "systemctl list-units --type=service --state=running --no-pager --no-legend 2>&1 | head -20"
        )
        deploys = srv_store.list_deploys()
        lines = [f"**Services on `{server['host']}`:**\n```\n{out or '(none)'}\n```"]
        if deploys:
            lines.append("\n**Recent deploys:**")
            for d in deploys[-5:]:
                lines.append(f"• `{d['service_name']}` — {d['status']} — {d['created_at'][:16]}")
        await followup(token, "\n".join(lines))

    elif sub == "update":
        service = o.get("service", "")
        if not service:
            return await followup(token, "❌ `service` is required. Use `/deploy status` to see running services.")

        server_name = o.get("server", "")
        server = srv_store.get(server_name) if server_name else srv_store.get_default()
        if not server:
            return await followup(token, "❌ No server configured. Use `/server add` first.")

        branch = o.get("branch", "main")
        start_cmd = o.get("start_cmd", "")

        await followup(token, f"🔄 Updating `{service}` on `{server['host']}`...\n_Pulling code → reinstalling deps → restarting → health check_")

        progress_msgs = []
        async def send_progress(msg):
            progress_msgs.append(msg)
            if len(progress_msgs) % 2 == 0 or "❌" in msg or "✅ Health" in msg:
                await followup(token, "\n".join(progress_msgs[-3:]))

        def _progress_cb(msg):
            progress_msgs.append(msg)
            asyncio.get_event_loop().call_soon_threadsafe(
                asyncio.ensure_future, send_progress(msg)
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: ssh.update_service(
            server=server, service_name=service,
            branch=branch, start_cmd=start_cmd or None,
            progress_cb=_progress_cb,
        ))

        steps_text = "\n".join(result["steps"])
        port = result.get("port", 0)

        if result["healthy"]:
            srv_store.record_deploy(
                project_name=service, server_name=server["name"],
                service_name=service, port=port, deploy_type="update",
                status="healthy", url=f"http://{server['host']}:{port}",
            )
            await followup(token,
                f"✅ **Update complete!**\n{steps_text}\n"
                f"🔒 Running on `{server['host']}` — private port `{port}`"
            )
        else:
            srv_store.record_deploy(
                project_name=service, server_name=server["name"],
                service_name=service, port=port, deploy_type="update",
                status="unhealthy", url="",
            )
            await followup_chunks(token, f"⚠️ **Update finished with issues:**\n{steps_text}")

    elif sub == "health":
        service = o.get("service", "")
        if not service:
            return await followup(token, "❌ `service` is required.")

        server_name = o.get("server", "")
        server = srv_store.get(server_name) if server_name else srv_store.get_default()
        if not server:
            return await followup(token, "❌ No server configured.")

        await followup(token, f"🔍 Checking health of `{service}` on `{server['host']}`...")

        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(None, lambda: ssh.get_service_status(server, service))

        icon = "✅" if status["active"] else "❌"
        lines = [
            f"{icon} **{service}** — {status['state']} ({status['sub_state']})",
            f"PID: `{status['pid']}`" if status["pid"] else "",
            f"Memory: `{status['memory']}`" if status["memory"] else "",
            f"Started: `{status['started_at']}`" if status["started_at"] else "",
            f"\n**Recent logs:**\n```\n{status['recent_logs'][:1000]}\n```",
        ]
        await followup(token, "\n".join(l for l in lines if l))

    elif sub == "rollback":
        deploy_id = o.get("deployment_id", "")
        await followup(token, f"⚠️ Rollback for `{deploy_id}` — pull previous commit and redeploy.\n_Manual rollback: run `/claude ask prompt:git revert HEAD && redeploy`_")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
