"""
/test command — visual testing, console logs, and automated test-fix loop.
"""
import asyncio
import json
import storage.projects as proj_store
import storage.sessions as sess_store
import layers.browser_layer as browser
import layers.test_loop as test_loop
from utils.discord_helpers import followup, followup_chunks, send_image_to_channel, send_message, opts


async def handle(sub: str, sub_opts: list, token: str, channel_id: str, user_id: str):
    o = opts(sub_opts)

    if sub == "screenshot":
        proj = proj_store.get_by_channel(channel_id)
        if not proj:
            return await followup(token, "❌ No active project. Use `/project use` first.")

        url = o.get("url", "")
        await followup(token, "📸 Taking screenshot with console capture...")
        try:
            if not url:
                url = await browser.start_server(proj["path"])
            img, console = await browser.screenshot_with_console(url)
            await send_image_to_channel(channel_id, img, "screenshot.png", "📸 Screenshot")

            if console and console != "(no console output)":
                await followup(token, f"**Console output:**\n```\n{console[:1500]}\n```")
            else:
                await followup(token, "✅ Screenshot taken. No console errors detected.")
        except Exception as e:
            await followup(token, f"❌ Failed: {e}")

    elif sub == "console":
        logs = browser.get_console_logs()
        if not logs:
            return await followup(token, "📝 No console logs captured yet. Take a screenshot first or run a test.")
        formatted = browser.format_console_logs(logs)
        await followup_chunks(token, f"**Browser Console Logs:**\n```\n{formatted}\n```")

    elif sub == "run":
        proj = proj_store.get_by_channel(channel_id)
        if not proj:
            return await followup(token, "❌ No active project. Use `/project use` first.")

        description = o.get("description", "")
        url = o.get("url", "")
        max_iter = int(o.get("iterations", "3"))

        if not description:
            return await followup(token, "❌ `description` is required — describe what the app does and what to test.")

        await followup(token,
            f"🧪 **Starting visual test loop** for **{proj['name']}**\n"
            f"Description: _{description}_\n"
            f"Max iterations: {max_iter}\n"
            f"_Codex will test → screenshot → evaluate → fix → repeat until it passes..._"
        )

        sess = sess_store.get_active_for_channel(channel_id)
        if not sess:
            sess = sess_store.create(proj["name"], channel_id, user_id)

        progress_queue = asyncio.Queue()

        def on_progress(msg):
            print(f"[test] {msg}")
            asyncio.get_event_loop().call_soon_threadsafe(progress_queue.put_nowait, msg)

        async def progress_sender():
            while True:
                msgs = []
                try:
                    msg = await asyncio.wait_for(progress_queue.get(), timeout=15)
                    msgs.append(msg)
                    while not progress_queue.empty():
                        msgs.append(await progress_queue.get())
                except asyncio.TimeoutError:
                    pass
                if msgs:
                    text = "\n".join(msgs[-5:])
                    await followup(token, text)

        sender_task = asyncio.create_task(progress_sender())

        try:
            result = await test_loop.run_test_loop(
                session_id=sess["id"],
                project_path=proj["path"],
                channel_id=channel_id,
                app_description=description,
                test_description=description,
                url=url or None,
                max_iterations=max_iter,
                progress_cb=on_progress,
            )
        except Exception as e:
            sender_task.cancel()
            return await followup(token, f"❌ Test loop failed: {e}")

        sender_task.cancel()
        await asyncio.sleep(1)

        icon = "✅" if result["passed"] else "⚠️"
        await followup(token,
            f"{icon} **Test loop complete!**\n"
            f"Score: **{result['final_score']}/10**\n"
            f"Iterations: {result['iterations']}\n"
            f"Result: {result['summary']}"
        )

    elif sub == "flow":
        proj = proj_store.get_by_channel(channel_id)
        if not proj:
            return await followup(token, "❌ No active project. Use `/project use` first.")

        steps_json = o.get("steps", "")
        url = o.get("url", "")
        record = o.get("record", "true").lower() != "false"

        if not steps_json:
            return await followup(token,
                "❌ `steps` is required — JSON array of test steps.\n"
                "Example: `[{\"action\": \"click\", \"selector\": \"#login-btn\"}, "
                "{\"action\": \"fill\", \"selector\": \"#email\", \"value\": \"test@test.com\"}]`"
            )

        try:
            steps = json.loads(steps_json)
        except json.JSONDecodeError as e:
            return await followup(token, f"❌ Invalid JSON: {e}")

        await followup(token,
            f"🧪 Running **{len(steps)} test steps** "
            f"{'with video recording' if record else 'without recording'}..."
        )

        try:
            if not url:
                url = await browser.start_server(proj["path"])

            result = await browser.run_test_flow(
                url=url, steps=steps, record=record,
                progress_cb=lambda msg: asyncio.get_event_loop().call_soon_threadsafe(
                    asyncio.ensure_future, followup(token, msg)
                ) if False else print(f"[test] {msg}"),
            )

            if result["screenshots"]:
                await send_image_to_channel(
                    channel_id, result["screenshots"][-1],
                    "test_result.png", "🧪 Final state after test flow"
                )

            if result.get("video_path"):
                try:
                    video_data = open(result["video_path"], "rb").read()
                    await send_image_to_channel(channel_id, video_data, "test.webm", "🎥 Test recording")
                except Exception:
                    pass

            lines = [f"✅ **Test flow complete** ({len(steps)} steps)"]
            if result["errors"]:
                lines.append(f"\n⚠️ Errors:\n" + "\n".join(f"• {e}" for e in result["errors"]))
            if result["console_logs"] and result["console_logs"] != "(no console output)":
                lines.append(f"\n**Console:**\n```\n{result['console_logs'][:800]}\n```")

            await followup(token, "\n".join(lines))

        except Exception as e:
            await followup(token, f"❌ Test flow failed: {e}")

    elif sub == "interact":
        proj = proj_store.get_by_channel(channel_id)
        if not proj:
            return await followup(token, "❌ No active project. Use `/project use` first.")

        action = o.get("action", "")
        selector = o.get("selector", "")
        value = o.get("value", "")

        if not action:
            return await followup(token, "❌ `action` is required (click, fill, type, press, scroll, upload, evaluate_js).")

        try:
            page = await browser._ensure_browser()

            if action == "click":
                img = await browser.click(selector)
            elif action == "fill":
                img = await browser.fill_input(selector, value)
            elif action == "type":
                img = await browser.type_text(selector, value)
            elif action == "press":
                img = await browser.press_key(value or selector)
            elif action == "scroll":
                img = await browser.scroll(int(value) if value else 500)
            elif action == "upload":
                img = await browser.upload_file(selector, value)
            elif action == "evaluate_js":
                result = await browser.evaluate_js(value or selector)
                return await followup(token, f"**JS Result:**\n```\n{result[:1500]}\n```")
            else:
                return await followup(token, f"❌ Unknown action: `{action}`")

            await send_image_to_channel(channel_id, img, "interact.png", f"🖱️ {action}: `{selector or value}`")
            console = browser.format_console_logs(browser.get_console_logs(clear=False))
            error_lines = [l for l in console.split("\n") if "error" in l.lower()]
            if error_lines:
                await followup(token, f"⚠️ Console errors after action:\n```\n{chr(10).join(error_lines[:5])}\n```")
            else:
                await followup(token, f"✅ `{action}` completed.")

        except Exception as e:
            await followup(token, f"❌ Action failed: {e}")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
