import storage.projects as proj_store
import layers.browser_layer as browser
from utils.discord_helpers import followup, send_image_to_channel, opts


def _get_proj(channel_id):
    proj = proj_store.get_by_channel(channel_id)
    if not proj:
        raise ValueError("No active project. Use `/project use` first.")
    return proj


async def handle(sub: str, sub_opts: list, token: str, channel_id: str):
    o = opts(sub_opts)

    if sub == "run":
        try:
            proj = _get_proj(channel_id)
        except ValueError as e:
            return await followup(token, f"❌ {e}")
        url = o.get("url", "")
        await followup(token, f"🚀 Starting dev server for **{proj['name']}**...")
        try:
            dev_url = await browser.start_server(proj["path"], url or None)
            await followup(token, f"✅ Dev server running at `{dev_url}`\nUse `/preview screenshot` to capture it.")
        except Exception as e:
            await followup(token, f"❌ Failed to start server: {e}")

    elif sub == "screenshot":
        url = o.get("url", "")
        await followup(token, "📸 Taking screenshot...")
        try:
            img = await browser.screenshot(url or None, full_page=False)
            await send_image_to_channel(channel_id, img, "screenshot.png", "📸 Desktop screenshot")
            await followup(token, "✅ Screenshot sent above.")
        except Exception as e:
            await followup(token, f"❌ Screenshot failed: {e}")

    elif sub == "mobile":
        url = o.get("url", "")
        await followup(token, "📱 Taking mobile screenshot...")
        try:
            img = await browser.screenshot_mobile(url or None)
            await send_image_to_channel(channel_id, img, "mobile.png", "📱 Mobile screenshot (iPhone 14 Pro)")
            await followup(token, "✅ Mobile screenshot sent above.")
        except Exception as e:
            await followup(token, f"❌ Mobile screenshot failed: {e}")

    elif sub == "scroll":
        pixels = int(o.get("pixels", 500))
        await followup(token, f"⬇️ Scrolling {pixels}px and capturing...")
        try:
            img = await browser.scroll(pixels)
            await send_image_to_channel(channel_id, img, "scroll.png", f"⬇️ After scrolling {pixels}px")
            await followup(token, "✅ Scroll screenshot sent above.")
        except Exception as e:
            await followup(token, f"❌ Scroll failed: {e}")

    elif sub == "click":
        selector = o.get("selector", "")
        if not selector:
            return await followup(token, "❌ `selector` is required.")
        await followup(token, f"🖱️ Clicking `{selector}`...")
        try:
            img = await browser.click(selector)
            await send_image_to_channel(channel_id, img, "click.png", f"🖱️ After clicking `{selector}`")
            await followup(token, "✅ Click screenshot sent above.")
        except Exception as e:
            await followup(token, f"❌ Click failed: {e}")

    elif sub == "stop":
        await browser.stop_server()
        await browser.close_browser()
        await followup(token, "✅ Dev server and browser closed.")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
