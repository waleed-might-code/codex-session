"""
make-live skill: end-to-end flow
Codex finalizes → preview → backend deploy → tunnel → frontend deploy → return URLs.
"""
import asyncio
import storage.projects as proj_store
import storage.servers as srv_store
import storage.cloudflare as cf_store
import layers.codex_exec as claude_exec
import layers.ssh_layer as ssh
import layers.browser_layer as browser
import layers.cloudflare_layer as cf_layer
import storage.sessions as sess_store
from utils.discord_helpers import followup, send_image_to_channel


async def run(token: str, channel_id: str, user_id: str, notes: str = ""):
    """Orchestrate full make-live workflow."""
    proj = proj_store.get_by_channel(channel_id)
    if not proj:
        return await followup(token, "❌ No active project. Use `/project use` first.")

    server = srv_store.get_default()
    has_cf = bool(cf_store.get_token())

    await followup(token, (
        f"🚀 **make-live** starting for **{proj['name']}**\n"
        f"Server: `{server['host'] if server else 'none'}`\n"
        f"Cloudflare: {'✅' if has_cf else '⚠️ not connected'}\n"
        f"_{notes or 'Full stack release'}_"
    ))

    # ── Step 1: Codex finalizes ───────────────────────────────────────────────
    sess = sess_store.get_active_for_channel(channel_id)
    if not sess:
        sess = sess_store.create(proj["name"], channel_id, user_id)

    await followup(token, "**[1/6]** 🤖 Asking Codex to prepare code for production...")
    finalize_prompt = (
        "Prepare this project for production deployment. "
        "Check for obvious errors, ensure imports are correct, and confirm the entry point is valid. "
        f"{'Additional notes: ' + notes if notes else ''}"
        "Give me a brief summary of what's ready."
    )
    claude_summary = await claude_exec.run(
        session_id=sess["id"], prompt=finalize_prompt, project_path=proj["path"]
    )
    await followup(token, f"**Codex:** {claude_summary[:1000]}")

    # ── Step 2: Preview screenshot ────────────────────────────────────────────
    await followup(token, "**[2/6]** 📸 Taking preview screenshot...")
    try:
        dev_url = await browser.start_server(proj["path"])
        img = await browser.screenshot(dev_url)
        await send_image_to_channel(channel_id, img, "preview.png", "📸 Pre-deploy preview")
        await browser.stop_server()
        await followup(token, "Screenshot captured.")
    except Exception as e:
        await followup(token, f"⚠️ Preview skipped: {e}")

    # ── Step 3: Backend deploy ────────────────────────────────────────────────
    backend_url = ""
    if server:
        await followup(token, f"**[3/6]** 🖥️ Deploying backend to `{server['host']}`...")
        service = proj["name"].lower().replace(" ", "-") + "-api"
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: ssh.deploy_service(server, service))
        port = result["port"]
        backend_url = f"http://{server['host']}:{port}"
        await followup(token, f"Backend: {'✅' if result['healthy'] else '⚠️'} private port `{port}` on `{server['host']}`")
    else:
        await followup(token, "**[3/6]** ⏭️ Skipping backend (no server configured)")

    # ── Step 4: Cloudflare tunnel ────────────────────────────────────────────
    public_backend_url = ""
    if has_cf and server:
        await followup(token, "**[4/6]** 🌐 Ensuring Cloudflare tunnel...")
        try:
            t_result = await cf_layer.ensure_tunnel(server["name"])
            tunnel = t_result["tunnel"]
            # Install on server if newly created
            if t_result["created"]:
                t_token = await cf_layer.get_tunnel_token(tunnel["tunnel_id"])
                install = await cf_layer.install_tunnel_on_server(server, t_token, port)
                await followup(token, f"Tunnel installed: {'✅' if install['ok'] else '⚠️'}")
            await followup(token, f"Tunnel: ✅ `{tunnel['tunnel_name']}`\nUse `/cloudflare hostname` to attach a subdomain.")
        except Exception as e:
            await followup(token, f"Tunnel: ⚠️ {e}")
    else:
        await followup(token, "**[4/6]** ⏭️ Skipping tunnel")

    # ── Step 5: Frontend deploy ───────────────────────────────────────────────
    frontend_url = ""
    if has_cf:
        await followup(token, "**[5/6]** 🌍 Deploying frontend to Cloudflare Pages...")
        try:
            pages = await cf_layer.deploy_pages(proj["path"], proj["name"])
            frontend_url = pages.get("url", "")
            cf_store.save_pages(proj["name"], pages["pages_project"], frontend_url)
            await followup(token, f"Frontend: {'✅' if pages['ok'] else '⚠️'} {frontend_url}")
        except Exception as e:
            await followup(token, f"Frontend: ⚠️ {e}")
    else:
        await followup(token, "**[5/6]** ⏭️ Skipping frontend (Cloudflare not connected)")

    # ── Step 6: Summary ───────────────────────────────────────────────────────
    await followup(token,
        f"**[6/6] 🎉 make-live complete!**\n\n"
        f"🌐 **Frontend:** {frontend_url or '(not deployed)'}\n"
        f"🔧 **Backend:** {backend_url or '(not deployed)'}\n"
        f"{'🔒 Backend is private — run `/cloudflare hostname` to expose it.' if backend_url and not public_backend_url else ''}"
    )
