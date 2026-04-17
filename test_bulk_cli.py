#!/usr/bin/env python3
"""CLI test for bulk spec parsing + Claude execution — no Discord needed."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from bot import _parse_numbered_specs
import layers.claude_exec as claude_exec
import storage.sessions as sess_store

PROJECT_PATH = "/root/projectexo/projects/greenflag"

# ── Minimal 2-spec test prompt ───────────────────────────────────────────────
TEST_PROMPT = """
You are building Flask apps. Each app should:
- Have a single app.py and templates/index.html
- Use Flask
- Run on the assigned port

1. Hello World App - A simple hello world Flask app that shows a styled greeting page with the current time.

2. Counter App - A Flask app with a button that increments a counter, showing the count on the page with nice styling.
""".strip()


def test_parse():
    print("=" * 60)
    print("TEST 1: Spec parsing")
    print("=" * 60)
    specs = _parse_numbered_specs(TEST_PROMPT)
    if not specs:
        print("FAIL: parser returned None")
        return None
    print(f"OK: parsed {len(specs)} specs")
    for s in specs:
        print(f"  #{s['index']} {s['name']}")
        print(f"    prompt length: {len(s['prompt'])} chars")
        print(f"    prompt preview: {s['prompt'][:100]}...")
    print()
    return specs


async def test_single_claude(spec, port):
    """Run Claude on a single spec and print progress."""
    tag = f"[#{spec['index']} {spec['name']}]"

    sess = sess_store.create(
        project_name="greenflag",
        channel_id=f"cli-test-{spec['index']}",
        user_id="cli-tester",
    )
    print(f"{tag} session: {sess['id']}")

    port_hint = (
        f"\n\nIMPORTANT: Use port {port} for this app's Flask server "
        f"(e.g. app.run(port={port})). Do NOT use port 5000."
    )
    prompt = spec["prompt"] + port_hint

    def on_progress(msg):
        print(f"{tag} {msg}")

    t0 = time.time()
    try:
        result = await claude_exec.run(
            session_id=sess["id"],
            prompt=prompt,
            project_path=PROJECT_PATH,
            progress_cb=on_progress,
            max_turns=10,
            channel_id=f"cli-test-{spec['index']}",
        )
        elapsed = time.time() - t0
        print(f"\n{tag} DONE in {elapsed:.1f}s")
        print(f"{tag} result preview: {result[:300]}...")
        return True
    except claude_exec.TurnLimitReached as e:
        elapsed = time.time() - t0
        print(f"\n{tag} STEP LIMIT in {elapsed:.1f}s")
        if e.partial_result:
            print(f"{tag} partial: {e.partial_result[:200]}...")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"\n{tag} ERROR after {elapsed:.1f}s: {e}")
        return False


async def test_parallel(specs):
    print("=" * 60)
    print("TEST 2: Parallel Claude execution (staggered 3s)")
    print("=" * 60)
    base_port = 5051  # use high ports to avoid conflicts

    async def staggered(spec, delay, port):
        if delay > 0:
            print(f"[#{spec['index']}] waiting {delay}s before start...")
            await asyncio.sleep(delay)
        return await test_single_claude(spec, port)

    tasks = [
        asyncio.create_task(staggered(s, i * 3, base_port + i))
        for i, s in enumerate(specs)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    print("\n" + "=" * 60)
    print("RESULTS:")
    for spec, result in zip(specs, results):
        status = "OK" if result is True else f"FAIL: {result}"
        print(f"  #{spec['index']} {spec['name']}: {status}")
    print("=" * 60)


async def main():
    print("Bulk CLI Test")
    print(f"Project: {PROJECT_PATH}")
    print(f"API: {os.getenv('ANTHROPIC_BASE_URL', 'default')}")
    print(f"Model: {os.getenv('CLAUDE_MODEL', 'default')}")
    print()

    # Test 1: parsing
    specs = test_parse()
    if not specs:
        sys.exit(1)

    # Test 2: run Claude on the parsed specs in parallel
    mode = sys.argv[1] if len(sys.argv) > 1 else "parallel"
    if mode == "parse-only":
        print("parse-only mode — skipping Claude execution")
        return

    if mode == "single":
        print("single mode — running only the first spec")
        await test_single_claude(specs[0], 5051)
    else:
        await test_parallel(specs)


if __name__ == "__main__":
    asyncio.run(main())
