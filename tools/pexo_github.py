#!/usr/bin/env python3
"""
pexo-github: Comprehensive GitHub CLI for Claude.

REPO MANAGEMENT:
  pexo-github repo create <name> [--private] [--desc "..."]
  pexo-github repo delete <name>
  pexo-github repo list
  pexo-github repo info <name>
  pexo-github repo set <name> --desc "..." [--private|--public] [--topics t1,t2]

PUSH / COMMIT:
  pexo-github push <repo> [--dir <path>] [--msg "..."] [--branch main] [--private]
  pexo-github commit [--msg "..."] [--dir <path>]

BRANCHES:
  pexo-github branch list <repo>
  pexo-github branch create <repo> <branch> [--from main]
  pexo-github branch delete <repo> <branch>

LINKS (always works — just constructs URLs):
  pexo-github link <repo>                        — repo homepage
  pexo-github link <repo> <file>                 — file on main branch
  pexo-github link <repo> <file> --branch <b>    — file on specific branch
  pexo-github link <repo> <file> --raw           — raw file content URL
  pexo-github link <repo> --releases             — releases page

FILES (read/write via GitHub API — no git needed):
  pexo-github file get <repo> <path> [--branch main]      — read file from repo
  pexo-github file put <repo> <path> <local_file> [--msg "..."]  — upload/update file
  pexo-github file delete <repo> <path> [--msg "..."]

RELEASES:
  pexo-github release create <repo> <tag> [--name "..."] [--notes "..."] [--draft]

PULL REQUESTS:
  pexo-github pr create <repo> --title "..." --body "..." --head <branch> [--base main]
  pexo-github pr list <repo>

SEARCH:
  pexo-github search <repo> <query>             — search code in repo
"""
import sys
import os
import json
import base64
import subprocess
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.github as gh_store
import httpx

def get_creds():
    token = gh_store.get_token()
    username = gh_store.get_username()
    if not token:
        print("ERROR: GitHub not connected. Use /github connect first.")
        sys.exit(1)
    return token, username

def headers():
    token, _ = get_creds()
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def api(method, path, data=None, params=None):
    url = f"https://api.github.com{path}"
    r = httpx.request(method, url, headers=headers(), json=data, params=params, timeout=20)
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body

def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)

# ── Repo ──────────────────────────────────────────────────────────────────────

def repo_create(name, private=False, desc=""):
    _, username = get_creds()
    status, data = api("POST", "/user/repos", {
        "name": name, "private": private,
        "description": desc, "auto_init": False
    })
    if status in (200, 201):
        print(f"✅ Created: {data['html_url']}")
        print(f"REPO_URL={data['html_url']}")
        print(f"CLONE_URL=https://github.com/{username}/{name}.git")
    elif status == 422:
        print(f"✅ Already exists: https://github.com/{username}/{name}")
        print(f"REPO_URL=https://github.com/{username}/{name}")
        print(f"CLONE_URL=https://github.com/{username}/{name}.git")
    else:
        die(f"{status} — {data.get('message', data)}")

def repo_delete(name):
    _, username = get_creds()
    status, data = api("DELETE", f"/repos/{username}/{name}")
    if status == 204:
        print(f"✅ Deleted '{name}'")
    else:
        die(f"{status} — {data.get('message', data)}")

def repo_list():
    status, data = api("GET", "/user/repos", params={"per_page": 50, "sort": "updated"})
    if status != 200:
        die(str(data))
    for r in data:
        vis = "private" if r["private"] else "public "
        print(f"  [{vis}] {r['name']:40s} {r['html_url']}")

def repo_info(name):
    _, username = get_creds()
    status, data = api("GET", f"/repos/{username}/{name}")
    if status != 200:
        die(f"{status} — {data.get('message', data)}")
    print(f"Name:        {data['full_name']}")
    print(f"URL:         {data['html_url']}")
    print(f"Description: {data.get('description') or '—'}")
    print(f"Visibility:  {'private' if data['private'] else 'public'}")
    print(f"Stars:       {data['stargazers_count']}")
    print(f"Default:     {data['default_branch']}")
    print(f"Clone URL:   https://github.com/{data['full_name']}.git")

def repo_set(name, desc=None, private=None, topics=None):
    _, username = get_creds()
    payload = {}
    if desc is not None:
        payload["description"] = desc
    if private is not None:
        payload["private"] = private
    if payload:
        status, data = api("PATCH", f"/repos/{username}/{name}", payload)
        if status != 200:
            die(f"{status} — {data.get('message', data)}")
        print(f"✅ Updated repo settings")
    if topics is not None:
        status, data = api("PUT", f"/repos/{username}/{name}/topics", {"names": topics})
        if status not in (200, 201):
            die(f"Topics update failed: {status}")
        print(f"✅ Topics set: {topics}")

# ── Push / Commit ─────────────────────────────────────────────────────────────

def sh(cmd, cwd=None):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0 and r.stderr.strip():
        print(f"  [stderr] {r.stderr.strip()[:200]}")
    return r.returncode

def push(repo, directory=None, message="Update from ProjectExo", branch="main", private=False):
    token, username = get_creds()
    cwd = os.path.abspath(directory or os.getcwd())
    repo_create(repo, private=private)
    remote = f"https://{token}@github.com/{username}/{repo}.git"

    if not os.path.exists(os.path.join(cwd, ".git")):
        sh("git init", cwd)
        sh('git config user.email "bot@projectexo.ai"', cwd)
        sh('git config user.name "ProjectExo"', cwd)
        sh(f"git checkout -b {branch}", cwd)

    remotes = subprocess.run("git remote", shell=True, cwd=cwd, capture_output=True, text=True).stdout
    if "origin" in remotes:
        sh(f"git remote set-url origin {remote}", cwd)
    else:
        sh(f"git remote add origin {remote}", cwd)

    sh("git add -A", cwd)
    staged = subprocess.run("git status --short", shell=True, cwd=cwd, capture_output=True, text=True).stdout.strip()
    if staged:
        sh(f'git commit -m "{message}"', cwd)
    else:
        print("Nothing new to commit — pushing existing commits.")

    code = sh(f"git push -u origin {branch} 2>&1", cwd)
    if code != 0:
        sh(f"git branch -M {branch} && git push -u origin {branch}", cwd)

    print(f"\n✅ Pushed!")
    print(f"REPO_URL=https://github.com/{username}/{repo}")
    print(f"BRANCH_URL=https://github.com/{username}/{repo}/tree/{branch}")

def commit_push(message="Update", directory=None):
    cwd = os.path.abspath(directory or os.getcwd())
    sh("git add -A", cwd)
    staged = subprocess.run("git status --short", shell=True, cwd=cwd, capture_output=True, text=True).stdout.strip()
    if staged:
        sh(f'git commit -m "{message}"', cwd)
        sh("git push", cwd)
        print("✅ Committed and pushed.")
    else:
        print("Nothing to commit.")

# ── Branches ──────────────────────────────────────────────────────────────────

def branch_list(repo):
    _, username = get_creds()
    status, data = api("GET", f"/repos/{username}/{repo}/branches")
    if status != 200:
        die(str(data))
    for b in data:
        print(f"  {b['name']}")

def branch_create(repo, branch, from_branch="main"):
    _, username = get_creds()
    # Get SHA of base branch
    status, data = api("GET", f"/repos/{username}/{repo}/git/refs/heads/{from_branch}")
    if status != 200:
        die(f"Base branch '{from_branch}' not found")
    sha = data["object"]["sha"]
    status, data = api("POST", f"/repos/{username}/{repo}/git/refs", {
        "ref": f"refs/heads/{branch}", "sha": sha
    })
    if status == 201:
        print(f"✅ Branch '{branch}' created from '{from_branch}'")
    else:
        die(f"{status} — {data.get('message', data)}")

def branch_delete(repo, branch):
    _, username = get_creds()
    status, _ = api("DELETE", f"/repos/{username}/{repo}/git/refs/heads/{branch}")
    if status == 204:
        print(f"✅ Branch '{branch}' deleted")
    else:
        die(f"Failed to delete branch")

# ── Links ─────────────────────────────────────────────────────────────────────

def link(repo, filepath=None, branch="main", raw=False, releases=False):
    _, username = get_creds()
    base = f"https://github.com/{username}/{repo}"
    if releases:
        print(f"{base}/releases")
    elif filepath:
        filepath = filepath.lstrip("/")
        if raw:
            print(f"https://raw.githubusercontent.com/{username}/{repo}/{branch}/{filepath}")
        else:
            print(f"{base}/blob/{branch}/{filepath}")
    else:
        print(base)

# ── Files (API — no git needed) ───────────────────────────────────────────────

def file_get(repo, path, branch="main"):
    _, username = get_creds()
    status, data = api("GET", f"/repos/{username}/{repo}/contents/{path.lstrip('/')}", 
                       params={"ref": branch})
    if status != 200:
        die(f"{status} — {data.get('message', data)}")
    if data.get("encoding") == "base64":
        content = base64.b64decode(data["content"]).decode(errors="replace")
        print(content)
    else:
        print(data.get("content", ""))

def file_put(repo, path, local_file, message=None):
    _, username = get_creds()
    path = path.lstrip("/")
    content = open(local_file, "rb").read()
    encoded = base64.b64encode(content).decode()
    msg = message or f"Update {path}"

    # Check if file exists to get its SHA
    status, existing = api("GET", f"/repos/{username}/{repo}/contents/{path}")
    sha = existing.get("sha") if status == 200 else None

    payload = {"message": msg, "content": encoded}
    if sha:
        payload["sha"] = sha

    status, data = api("PUT", f"/repos/{username}/{repo}/contents/{path}", payload)
    if status in (200, 201):
        print(f"✅ File uploaded: https://github.com/{username}/{repo}/blob/main/{path}")
        print(f"FILE_URL=https://github.com/{username}/{repo}/blob/main/{path}")
        print(f"RAW_URL=https://raw.githubusercontent.com/{username}/{repo}/main/{path}")
    else:
        die(f"{status} — {data.get('message', data)}")

def file_delete(repo, path, message=None):
    _, username = get_creds()
    path = path.lstrip("/")
    status, data = api("GET", f"/repos/{username}/{repo}/contents/{path}")
    if status != 200:
        die(f"File not found: {path}")
    sha = data["sha"]
    msg = message or f"Delete {path}"
    status, data = api("DELETE", f"/repos/{username}/{repo}/contents/{path}", 
                       {"message": msg, "sha": sha})
    if status == 200:
        print(f"✅ Deleted {path}")
    else:
        die(f"{status} — {data.get('message', data)}")

# ── Releases ──────────────────────────────────────────────────────────────────

def release_create(repo, tag, name=None, notes="", draft=False):
    _, username = get_creds()
    status, data = api("POST", f"/repos/{username}/{repo}/releases", {
        "tag_name": tag, "name": name or tag,
        "body": notes, "draft": draft
    })
    if status == 201:
        print(f"✅ Release created: {data['html_url']}")
        print(f"RELEASE_URL={data['html_url']}")
    else:
        die(f"{status} — {data.get('message', data)}")

# ── Pull Requests ─────────────────────────────────────────────────────────────

def pr_create(repo, title, body="", head="main", base="main"):
    _, username = get_creds()
    status, data = api("POST", f"/repos/{username}/{repo}/pulls", {
        "title": title, "body": body, "head": head, "base": base
    })
    if status == 201:
        print(f"✅ PR created: {data['html_url']}")
        print(f"PR_URL={data['html_url']}")
    else:
        die(f"{status} — {data.get('message', data)}")

def pr_list(repo):
    _, username = get_creds()
    status, data = api("GET", f"/repos/{username}/{repo}/pulls")
    if status != 200:
        die(str(data))
    if not data:
        print("No open PRs.")
        return
    for pr in data:
        print(f"  #{pr['number']} {pr['title']} [{pr['head']['ref']} → {pr['base']['ref']}]")
        print(f"    {pr['html_url']}")

# ── Search ────────────────────────────────────────────────────────────────────

def search(repo, query):
    _, username = get_creds()
    q = f"{query} repo:{username}/{repo}"
    status, data = api("GET", "/search/code", params={"q": q, "per_page": 10})
    if status != 200:
        die(str(data))
    items = data.get("items", [])
    if not items:
        print("No results found.")
        return
    for item in items:
        print(f"  {item['path']} — {item['html_url']}")

# ── Main ──────────────────────────────────────────────────────────────────────

def parse_flags(args, *flags):
    """Extract --flag value pairs from args list."""
    result = {}
    remaining = []
    i = 0
    while i < len(args):
        matched = False
        for f in flags:
            if args[i] == f and i+1 < len(args):
                result[f.lstrip("-")] = args[i+1]
                i += 2
                matched = True
                break
            elif args[i] == f:  # boolean flag
                result[f.lstrip("-")] = True
                i += 1
                matched = True
                break
        if not matched:
            remaining.append(args[i])
            i += 1
    return result, remaining

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    rest = args[1:]

    if cmd == "repo":
        sub = rest[0] if rest else ""
        if sub == "create":
            flags, pos = parse_flags(rest[1:], "--private", "--desc")
            repo_create(pos[0], private="private" in flags, desc=flags.get("desc",""))
        elif sub == "delete":
            repo_delete(rest[1])
        elif sub == "list":
            repo_list()
        elif sub == "info":
            repo_info(rest[1])
        elif sub == "set":
            flags, _ = parse_flags(rest[2:], "--desc", "--private", "--public", "--topics")
            private = True if "private" in flags else (False if "public" in flags else None)
            topics = flags["topics"].split(",") if "topics" in flags else None
            repo_set(rest[1], desc=flags.get("desc"), private=private, topics=topics)

    elif cmd == "push":
        flags, pos = parse_flags(rest[1:], "--dir", "--msg", "--branch", "--private")
        push(rest[0], directory=flags.get("dir"), message=flags.get("msg","Update from ProjectExo"),
             branch=flags.get("branch","main"), private="private" in flags)

    elif cmd == "commit":
        flags, _ = parse_flags(rest, "--msg", "--dir")
        commit_push(message=flags.get("msg","Update"), directory=flags.get("dir"))

    elif cmd == "branch":
        sub = rest[0]
        if sub == "list":
            branch_list(rest[1])
        elif sub == "create":
            flags, _ = parse_flags(rest[2:], "--from")
            branch_create(rest[1], rest[2] if len(rest) > 2 else die("branch name required"),
                         from_branch=flags.get("from","main"))
        elif sub == "delete":
            branch_delete(rest[1], rest[2])

    elif cmd == "link":
        flags, pos = parse_flags(rest[1:], "--branch", "--raw", "--releases")
        filepath = pos[0] if pos else None
        link(rest[0], filepath=filepath, branch=flags.get("branch","main"),
             raw="raw" in flags, releases="releases" in flags)

    elif cmd == "file":
        sub = rest[0]
        if sub == "get":
            flags, _ = parse_flags(rest[2:], "--branch")
            file_get(rest[1], rest[2], branch=flags.get("branch","main"))
        elif sub == "put":
            flags, _ = parse_flags(rest[3:], "--msg")
            file_put(rest[1], rest[2], rest[3], message=flags.get("msg"))
        elif sub == "delete":
            flags, _ = parse_flags(rest[2:], "--msg")
            file_delete(rest[1], rest[2], message=flags.get("msg"))

    elif cmd == "release":
        if rest[0] == "create":
            flags, _ = parse_flags(rest[2:], "--name", "--notes", "--draft")
            release_create(rest[1], rest[2] if len(rest) > 2 else die("tag required"),
                          name=flags.get("name"), notes=flags.get("notes",""), draft="draft" in flags)

    elif cmd == "pr":
        sub = rest[0]
        if sub == "create":
            flags, _ = parse_flags(rest[1:], "--title", "--body", "--head", "--base")
            pr_create(rest[1] if len(rest) > 1 else die("repo required"),
                     title=flags.get("title",""), body=flags.get("body",""),
                     head=flags.get("head","main"), base=flags.get("base","main"))
        elif sub == "list":
            pr_list(rest[1])

    elif cmd == "search":
        search(rest[0], " ".join(rest[1:]))

    else:
        print(f"Unknown command: {cmd}\n")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
