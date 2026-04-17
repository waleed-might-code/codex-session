"""
Visual testing loop: automated test → screenshot → Codex vision eval → fix → repeat.
Runs a browser test flow, sends screenshots to Codex for evaluation,
and iterates fixes until the app looks correct or max iterations are reached.
"""
import asyncio
import io
import json
from typing import Callable, Optional

import layers.browser_layer as browser
import layers.codex_exec as claude_exec
import storage.sessions as sess_store
from utils.discord_helpers import send_image_to_channel, send_message

MAX_ITERATIONS = 5


async def _evaluate_screenshot(
    image_data: bytes,
    console_logs: str,
    project_path: str,
    app_description: str,
    test_description: str,
    iteration: int,
) -> dict:
    """Send screenshot + console logs to Codex for evaluation."""

    try:
        from PIL import Image
        pil = Image.open(io.BytesIO(image_data))
        pil.thumbnail((1024, 1024))
        buf = io.BytesIO()
        pil.save(buf, format="PNG", optimize=True)
        image_data = buf.getvalue()
    except Exception:
        pass

    prompt_parts = [
        f"You are evaluating a web application (iteration {iteration}/{MAX_ITERATIONS}).",
        f"\nApp description: {app_description}",
        f"\nTest being performed: {test_description}",
    ]
    if console_logs and console_logs != "(no console output)":
        prompt_parts.append(f"\nBrowser console output:\n```\n{console_logs[:2000]}\n```")

    prompt_parts.append(
        "\nAnalyze this screenshot carefully. Respond in JSON format only:\n"
        "{\n"
        '  "status": "pass" or "fail",\n'
        '  "score": 1-10 (visual quality and correctness),\n'
        '  "issues": ["list of specific problems found"],\n'
        '  "suggestions": ["specific fixes to apply"],\n'
        '  "summary": "one line overall assessment"\n'
        "}"
    )

    try:
        text, _ = await claude_exec.run_once(
            prompt="\n".join(prompt_parts),
            project_path=project_path,
            image_data=image_data,
            image_media_type="image/png",
            sandbox="read-only",
        )
        return claude_exec.extract_json(text)
    except (json.JSONDecodeError, Exception) as e:
        return {
            "status": "fail",
            "score": 0,
            "issues": [f"Evaluation failed: {e}"],
            "suggestions": [],
            "summary": "Could not evaluate screenshot",
        }


async def run_test_loop(
    session_id: str,
    project_path: str,
    channel_id: str,
    app_description: str = "",
    test_steps: list[dict] = None,
    test_description: str = "",
    url: str = None,
    max_iterations: int = None,
    progress_cb: Callable[[str], None] = None,
) -> dict:
    """
    Automated visual testing loop:
    1. Start dev server + open app
    2. Run test steps (if any)
    3. Screenshot + capture console
    4. Send to Codex for evaluation
    5. If issues found → ask Codex to fix → repeat from step 2
    6. Send progress and screenshots to Discord throughout

    Returns {"passed": bool, "iterations": int, "final_score": int, "summary": str}
    """
    max_iter = max_iterations or MAX_ITERATIONS

    def report(msg):
        print(f"[test_loop] {msg}")
        if progress_cb:
            progress_cb(msg)

    # Start dev server
    report("🚀 Starting dev server...")
    try:
        dev_url = url or await browser.start_server(project_path)
    except Exception as e:
        return {"passed": False, "iterations": 0, "final_score": 0, "summary": f"Failed to start server: {e}"}

    report(f"🌐 Server at `{dev_url}`")

    passed = False
    final_score = 0
    summary = ""
    iteration = 0

    for iteration in range(1, max_iter + 1):
        report(f"\n**━━━ Iteration {iteration}/{max_iter} ━━━**")

        # Run test steps if provided
        if test_steps:
            report("🧪 Running test steps...")
            result = await browser.run_test_flow(
                url=dev_url, steps=test_steps, record=(iteration == 1),
                progress_cb=lambda msg: report(f"  {msg}"),
            )
            screenshots = result["screenshots"]
            console_logs = result["console_logs"]
            errors = result["errors"]

            if errors:
                report(f"⚠️ Test errors: {'; '.join(errors[:3])}")

            # Send video on first iteration
            if iteration == 1 and result.get("video_path"):
                try:
                    video_data = open(result["video_path"], "rb").read()
                    from utils.discord_helpers import send_image_to_channel
                    await send_image_to_channel(channel_id, video_data, "test_recording.webm", "🎥 Test recording")
                except Exception as e:
                    report(f"⚠️ Video send failed: {e}")
        else:
            # Just screenshot
            report("📸 Taking screenshot...")
            img, console_logs = await browser.screenshot_with_console(dev_url)
            screenshots = [img]
            errors = []

        # Send latest screenshot to Discord
        if screenshots:
            latest_img = screenshots[-1]
            await send_image_to_channel(
                channel_id, latest_img, f"test_iter_{iteration}.png",
                f"🧪 Iteration {iteration}/{max_iter}"
            )

        # Send console logs if there are errors/warnings
        if console_logs and console_logs != "(no console output)":
            error_lines = [l for l in console_logs.split("\n") if "error" in l.lower() or "warn" in l.lower()]
            if error_lines:
                report(f"🖥️ Console issues:\n```\n{chr(10).join(error_lines[:10])}\n```")

        # Evaluate with Codex
        report("🤖 Codex is evaluating the screenshot...")
        eval_result = await _evaluate_screenshot(
            image_data=screenshots[-1] if screenshots else b"",
            console_logs=console_logs,
            project_path=project_path,
            app_description=app_description,
            test_description=test_description,
            iteration=iteration,
        )

        score = eval_result.get("score", 0)
        status = eval_result.get("status", "fail")
        issues = eval_result.get("issues", [])
        suggestions = eval_result.get("suggestions", [])
        eval_summary = eval_result.get("summary", "")

        final_score = score
        summary = eval_summary

        report(f"📊 Score: **{score}/10** — {eval_summary}")

        if status == "pass" and score >= 7:
            passed = True
            report(f"✅ **PASSED** — app looks good (score: {score}/10)")
            break

        if iteration >= max_iter:
            report(f"⏰ Max iterations reached. Final score: {score}/10")
            break

        # Build fix prompt from issues and suggestions
        fix_parts = [
            f"The visual QA test found issues (score: {score}/10).",
            f"Evaluation: {eval_summary}",
        ]
        if issues:
            fix_parts.append(f"\nIssues found:\n" + "\n".join(f"- {i}" for i in issues))
        if suggestions:
            fix_parts.append(f"\nSuggested fixes:\n" + "\n".join(f"- {s}" for s in suggestions))
        if console_logs and console_logs != "(no console output)":
            error_logs = [l for l in console_logs.split("\n") if "error" in l.lower()]
            if error_logs:
                fix_parts.append(f"\nConsole errors:\n" + "\n".join(error_logs[:5]))

        fix_parts.append(
            "\nFix these issues. Make targeted changes only — don't rewrite everything. "
            "After fixing, the app will be re-screenshotted and re-evaluated automatically."
        )
        fix_prompt = "\n".join(fix_parts)

        report("🔧 Asking Codex to fix issues...")
        try:
            fix_result = await claude_exec.run(
                session_id=session_id,
                prompt=fix_prompt,
                project_path=project_path,
                progress_cb=lambda msg: report(f"  {msg}"),
                channel_id=channel_id,
                image_data=screenshots[-1] if screenshots else None,
                image_media_type="image/png",
            )
            report(f"🔧 Fix applied: {fix_result[:200]}")
        except claude_exec.TurnLimitReached as e:
            report(f"⚠️ Codex hit step limit during fix: {e.partial_result[:100]}")
        except Exception as e:
            report(f"❌ Fix failed: {e}")
            break

        # Restart dev server to pick up changes
        report("🔄 Restarting dev server...")
        await browser.stop_server()
        await asyncio.sleep(2)
        try:
            dev_url = await browser.start_server(project_path)
        except Exception as e:
            report(f"❌ Server restart failed: {e}")
            break

    return {
        "passed": passed,
        "iterations": iteration,
        "final_score": final_score,
        "summary": summary,
    }
