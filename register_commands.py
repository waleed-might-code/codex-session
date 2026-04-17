"""
Register all slash commands as guild commands (instant propagation).
Run once: python register_commands.py
"""
import os, base64
import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1066653561695502357")
APP_ID = base64.b64decode(BOT_TOKEN.split(".")[0] + "==").decode()
API = f"https://discord.com/api/v10/applications/{APP_ID}/guilds/{GUILD_ID}/commands"
HEADERS = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}

# ── Option type constants ─────────────────────────────────────────────────────
SUB = 1   # SUBCOMMAND
STR = 3   # STRING
INT = 4   # INTEGER
BOOL = 5  # BOOLEAN

def s(name, desc, required=False): return {"type": STR, "name": name, "description": desc, "required": required}
def i(name, desc, required=False): return {"type": INT, "name": name, "description": desc, "required": required}
def sub(name, desc, opts=None):    return {"type": SUB, "name": name, "description": desc, "options": opts or []}

COMMANDS = [
    {"name": "ping", "description": "Check if ProjectExo is online"},

    # ── /project ──────────────────────────────────────────────────────────────
    {"name": "project", "description": "Manage local projects", "options": [
        sub("add",    "Add a project", [s("name","Project name",True), s("path","Absolute path (optional, defaults to projects/<name>)"), s("description","Description")]),
        sub("list",   "List all projects"),
        sub("use",    "Set active project for this channel", [s("name","Project name",True)]),
        sub("info",   "Show active project info"),
        sub("remove", "Remove a project", [s("name","Project name",True)]),
    ]},

    # ── /files ────────────────────────────────────────────────────────────────
    {"name": "files", "description": "Browse project files", "options": [
        sub("tree", "Show directory tree", [s("path","Subdirectory (default: root)"), i("depth","Max depth (default: 3)")]),
        sub("find", "Find files by name", [s("query","Filename pattern",True)]),
    ]},

    # ── /file ─────────────────────────────────────────────────────────────────
    {"name": "file", "description": "View file contents", "options": [
        sub("view", "View full file", [s("path","File path relative to project",True)]),
        sub("head", "View first N lines", [s("path","File path",True), i("lines","Number of lines (default: 20)")]),
        sub("tail", "View last N lines",  [s("path","File path",True), i("lines","Number of lines (default: 20)")]),
    ]},

    # ── /codex ────────────────────────────────────────────────────────────────
    {"name": "codex", "description": "Codex coding agent", "options": [
        sub("ask",      "Send a prompt to Codex",          [s("prompt","Your task or question",True)]),
        sub("continue", "Continue previous Codex session", [s("prompt","Follow-up instruction")]),
        sub("auto",     "Auto-continue until task is done", [s("prompt","Task or follow-up"), i("rounds","Max auto-continue rounds (default: 5)")]),
        sub("thread",   "Run a task in a new Discord thread", [s("prompt","Task to run in thread",True), s("name","Thread name (optional)")]),
        sub("bulk",     "Run same prompt in N parallel threads", [s("prompt","Task to run in each thread",True), i("count","Number of threads (1-10, default: 3)"), s("name","Thread name prefix (default: Task)")]),
        sub("diff",     "Show git diff of Codex's changes"),
        sub("status",   "Show session and git status"),
        sub("plan",     "Ask Codex to plan (no edits)",    [s("prompt","What to plan",True)]),
        sub("fix",      "Ask Codex to find and fix an issue", [s("prompt","Describe the issue",True)]),
        sub("stop",     "Close current Codex session"),
        sub("limit",    "Set max steps for this session", [i("steps","Max steps (default: 40)")]),
    ]},

    # ── /claude (legacy alias) ───────────────────────────────────────────────
    {"name": "claude", "description": "Legacy alias for Codex", "options": [
        sub("ask",      "Send a prompt to Codex",          [s("prompt","Your task or question",True)]),
        sub("continue", "Continue previous Codex session", [s("prompt","Follow-up instruction")]),
        sub("auto",     "Auto-continue until task is done", [s("prompt","Task or follow-up"), i("rounds","Max auto-continue rounds (default: 5)")]),
        sub("thread",   "Run a task in a new Discord thread", [s("prompt","Task to run in thread",True), s("name","Thread name (optional)")]),
        sub("bulk",     "Run same prompt in N parallel threads", [s("prompt","Task to run in each thread",True), i("count","Number of threads (1-10, default: 3)"), s("name","Thread name prefix (default: Task)")]),
        sub("diff",     "Show git diff of Codex's changes"),
        sub("status",   "Show session and git status"),
        sub("plan",     "Ask Codex to plan (no edits)",    [s("prompt","What to plan",True)]),
        sub("fix",      "Ask Codex to find and fix an issue", [s("prompt","Describe the issue",True)]),
        sub("stop",     "Close current Codex session"),
        sub("limit",    "Set max steps for this session", [i("steps","Max steps (default: 40)")]),
    ]},

    # ── /session ──────────────────────────────────────────────────────────────
    {"name": "session", "description": "Manage Codex sessions", "options": [
        sub("list",   "List active sessions"),
        sub("current","Show current channel session"),
        sub("history","Show stored transcript history", [s("id","Session ID"), s("project","Project name"), i("limit","Max messages (default: 20)")]),
        sub("resume", "Resume a closed session", [s("id","Session ID",True)]),
        sub("close",  "Close a session",         [s("id","Session ID")]),
    ]},

    # ── /discord ──────────────────────────────────────────────────────────────
    {"name": "discord", "description": "Native Discord actions for messages, scheduling, and threads", "options": [
        sub("send",     "Send a Discord message", [s("message","Message content",True), s("channel","Target channel or thread id")]),
        sub("schedule", "Schedule a Discord message", [s("message","Message content",True), i("minutes","Delay in minutes"), s("at","UTC timestamp like 2026-04-18T18:00:00Z"), s("channel","Target channel or thread id")]),
        sub("jobs",     "List scheduled Discord jobs", [s("status","pending, sent, failed, cancelled")]),
        sub("cancel",   "Cancel a scheduled Discord job", [s("id","Job id",True)]),
        sub("thread",   "Create a standalone Discord thread", [s("name","Thread name",True), s("message","Optional starter message"), s("channel","Target channel id")]),
    ]},

    # ── /preview ──────────────────────────────────────────────────────────────
    {"name": "preview", "description": "Browser preview and screenshots", "options": [
        sub("run",        "Start local dev server", [s("url","Override URL")]),
        sub("screenshot", "Take desktop screenshot", [s("url","URL to capture")]),
        sub("mobile",     "Take mobile screenshot",  [s("url","URL to capture")]),
        sub("scroll",     "Scroll and screenshot",   [i("pixels","Pixels to scroll (default: 500)")]),
        sub("click",      "Click element and screenshot", [s("selector","CSS selector",True)]),
        sub("stop",       "Stop dev server and browser"),
    ]},

    # ── /server ───────────────────────────────────────────────────────────────
    {"name": "server", "description": "Manage SSH deployment servers", "options": [
        sub("add",       "Add server (password auth)", [s("name","Server alias",True), s("host","IP or hostname",True), s("username","SSH user",True), s("password","SSH password")]),
        sub("add-key",   "Add server (SSH key auth)",  [s("name","Server alias",True), s("host","IP or hostname",True), s("username","SSH user",True), s("private_key","PEM private key",True)]),
        sub("list",      "List all servers"),
        sub("test",      "Test SSH connectivity",      [s("name","Server alias (default: active)")]),
        sub("use",       "Set default server",         [s("name","Server alias",True)]),
        sub("logs",      "View service logs",          [s("service","Service name",True), s("name","Server alias"), i("tail_lines","Lines (default: 50)")]),
        sub("bootstrap", "Harden server: create deploy user + key", [s("name","Server alias")]),
    ]},

    # ── /cloudflare ───────────────────────────────────────────────────────────
    {"name": "cloudflare", "description": "Manage Cloudflare resources", "options": [
        sub("connect",  "Connect Cloudflare account",         [s("token","Cloudflare API token",True)]),
        sub("domains",  "List zones/domains"),
        sub("tunnel",   "Create or reuse tunnel for server",  [s("server","Server alias")]),
        sub("hostname", "Attach public hostname to tunnel",   [s("subdomain","Subdomain (e.g. api)",True), s("zone","Zone name or ID",True), s("server","Server alias"), s("service","Service name on the server"), i("port","Override port")]),
        sub("links",    "Show all active public links"),
    ]},

    # ── /deploy ───────────────────────────────────────────────────────────────
    {"name": "deploy", "description": "Deploy projects to servers", "options": [
        sub("api",      "Deploy backend API", [s("project","Project name override"), s("service","Service name"), s("repo","Git repo URL"), s("branch","Branch (default: main)"), s("start_cmd","Override start command"), s("server","Server alias")]),
        sub("web",      "Deploy frontend to Cloudflare Pages", [s("project","Project name override"), s("target","pages or workers (default: pages)"), s("branch","Branch (default: main)")]),
        sub("full",     "Full-stack deploy",  [s("server","Server alias"), s("frontend_target","pages or workers (default: pages)")]),
        sub("update",   "Update a deployed service (git pull + deps + restart)", [s("service","Service name",True), s("branch","Branch (default: main)"), s("start_cmd","Override start command"), s("server","Server alias")]),
        sub("health",   "Check detailed health of a deployed service", [s("service","Service name",True), s("server","Server alias")]),
        sub("status",   "Check deploy status", [s("server","Server alias")]),
        sub("rollback", "Roll back a deploy",  [s("deployment_id","Deploy ID",True)]),
    ]},

    # ── /test ─────────────────────────────────────────────────────────────────
    {"name": "test", "description": "Visual testing: screenshots with console, test flows, and auto test-fix loop", "options": [
        sub("screenshot", "Screenshot with browser console capture", [s("url","URL to capture")]),
        sub("console",    "Show captured browser console logs"),
        sub("run",        "Auto test-fix loop: screenshot → Codex eval → fix → repeat", [s("description","What the app does and what to test",True), s("url","URL to test"), i("iterations","Max fix iterations (default: 3)")]),
        sub("flow",       "Run a sequence of browser test steps (JSON)", [s("steps","JSON array of test steps",True), s("url","URL to test"), s("record","Record video: true/false (default: true)")]),
        sub("interact",   "Single browser action (click, fill, type, press, scroll)", [s("action","Action: click, fill, type, press, scroll, upload, evaluate_js",True), s("selector","CSS selector"), s("value","Value for fill/type, key for press, pixels for scroll")]),
    ]},

    # ── /github ───────────────────────────────────────────────────────────────
    {"name": "github", "description": "Connect GitHub for repo creation, push, and sharing", "options": [
        {"name": "connect", "description": "Connect your GitHub account", "type": 1, "options": [
            s("token", "GitHub Personal Access Token (needs repo scope)", required=True),
            s("username", "Your GitHub username", required=True),
        ]},
        {"name": "status", "description": "Show GitHub connection status", "type": 1, "options": []},
        {"name": "disconnect", "description": "Disconnect GitHub", "type": 1, "options": []},
    ]},

    # ── /make-live ────────────────────────────────────────────────────────────
    {"name": "make-live", "description": "One-command full-stack release: Codex → preview → deploy → tunnel → go live", "options": [
        s("notes", "Optional release notes or instructions"),
    ]},
]


def register():
    resp = httpx.put(API, headers=HEADERS, json=COMMANDS, timeout=30)
    if resp.status_code == 200:
        cmds = resp.json()
        print(f"✅ Registered {len(cmds)} commands:")
        for c in cmds:
            print(f"   /{c['name']}")
    else:
        print(f"❌ Failed: {resp.status_code}")
        print(resp.text[:500])


if __name__ == "__main__":
    register()
