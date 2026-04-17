import os
import subprocess
import mimetypes
import storage.projects as proj_store
from utils.discord_helpers import followup, followup_chunks, send_file, opts
from utils.security import safe_relative, truncate


def _get_project(channel_id: str):
    proj = proj_store.get_by_channel(channel_id)
    if not proj:
        raise ValueError("No active project. Use `/project use` first.")
    return proj


async def handle_files(sub: str, sub_opts: list, token: str, channel_id: str):
    o = opts(sub_opts)

    if sub == "tree":
        proj = _get_project(channel_id)
        path = o.get("path", ".")
        depth = int(o.get("depth", 3))
        try:
            target = safe_relative(proj["path"], path)
        except ValueError as e:
            return await followup(token, f"❌ {e}")
        lines, shown = [], 0
        for root, dirs, files in os.walk(target):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", ".git", "dist", ".next"})
            level = root.replace(target, "").count(os.sep)
            if level >= depth:
                continue
            indent = "  " * level
            lines.append(f"{indent}📁 {os.path.basename(root)}/")
            for f in sorted(files):
                fpath = os.path.join(root, f)
                try:
                    sz = os.path.getsize(fpath)
                    sz_str = f"{sz/1024:.1f}KB" if sz >= 1024 else f"{sz}B"
                except OSError:
                    sz_str = "?"
                lines.append(f"{indent}  📄 {f}  ({sz_str})")
                shown += 1
                if shown > 300:
                    lines.append("  … (truncated)")
                    break
            if shown > 300:
                break
        tree_text = "\n".join(lines) or "(empty)"
        rel = os.path.relpath(target, proj["path"])
        header = f"📂 **{proj['name']}**/{'' if rel == '.' else rel}\nUse `/file view <path>` to read or download any file.\n\n"
        await followup(token, header)
        await followup_chunks(token, tree_text, code_lang="")

    elif sub == "find":
        proj = _get_project(channel_id)
        query = o.get("query", "")
        out = subprocess.run(
            f"find . -iname '*{query}*' ! -path '*/node_modules/*' ! -path '*/.git/*' | head -30",
            shell=True, cwd=proj["path"], capture_output=True, text=True
        ).stdout.strip()
        await followup(token, f"**Files matching `{query}`:**\n```\n{out or '(none found)'}\n```")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")


async def handle_file(sub: str, sub_opts: list, token: str, channel_id: str):  # noqa: C901
    o = opts(sub_opts)

    try:
        proj = _get_project(channel_id)
    except ValueError as e:
        return await followup(token, f"❌ {e}")

    path = o.get("path", "")
    if not path:
        return await followup(token, "❌ `path` is required.")

    try:
        full = safe_relative(proj["path"], path)
    except ValueError as e:
        return await followup(token, f"❌ {e}")

    if sub == "view":
        if not os.path.isfile(full):
            return await followup(token, f"❌ File not found: `{path}`")

        file_bytes = open(full, "rb").read()
        fname = os.path.basename(full)
        size = len(file_bytes)
        ext = os.path.splitext(path)[1].lstrip(".")
        mime, _ = mimetypes.guess_type(fname)
        content_type = mime or "application/octet-stream"

        is_text = (mime and mime.startswith("text/")) or ext in {
            "py", "js", "ts", "jsx", "tsx", "html", "css", "json", "yaml", "yml",
            "toml", "ini", "cfg", "env", "md", "txt", "sh", "bash", "scad", "sql",
            "rs", "go", "java", "c", "cpp", "h", "cs", "rb", "php", "swift", "kt",
        }

        if is_text:
            text = file_bytes.decode("utf-8", errors="replace")
            lines_all = text.splitlines()
            preview = "\n".join(lines_all[:40])
            tail_note = f"\n… ({len(lines_all) - 40} more lines — see attachment)" if len(lines_all) > 40 else ""
            caption = f"📄 `{fname}` — {len(lines_all)} lines, {size:,} bytes"
            # Send the raw file to the channel (renders inline + downloadable)
            await send_file(channel_id, file_bytes, fname, caption=caption, content_type=content_type)
            # Inline code preview
            await followup_chunks(token, preview + tail_note, code_lang=ext)
        else:
            # Images, PDFs, ZIPs, etc. — send via channel message so Discord renders them properly
            sz_str = f"{size/1024:.1f} KB" if size >= 1024 else f"{size} B"
            caption = f"📎 `{fname}` — {sz_str}"
            await followup(token, caption)  # acknowledge the slash command
            await send_file(channel_id, file_bytes, fname, caption="", content_type=content_type)

    elif sub == "head":
        lines = int(o.get("lines", 20))
        if not os.path.isfile(full):
            return await followup(token, f"❌ File not found: `{path}`")
        fname = os.path.basename(full)
        with open(full, errors="replace") as f:
            head = "".join(f.readlines()[:lines])
        ext = os.path.splitext(path)[1].lstrip(".")
        await followup(token, f"📄 `{fname}` — first {lines} lines:")
        await followup_chunks(token, head, code_lang=ext)

    elif sub == "tail":
        lines = int(o.get("lines", 20))
        if not os.path.isfile(full):
            return await followup(token, f"❌ File not found: `{path}`")
        fname = os.path.basename(full)
        with open(full, errors="replace") as f:
            all_lines = f.readlines()
        tail = "".join(all_lines[-lines:])
        ext = os.path.splitext(path)[1].lstrip(".")
        await followup(token, f"📄 `{fname}` — last {lines} lines:")
        await followup_chunks(token, tail, code_lang=ext)

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
