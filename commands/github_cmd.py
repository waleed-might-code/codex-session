"""
/github connect token:<PAT> username:<handle>
/github status
/github disconnect
"""
import storage.github as gh_store
from utils.discord_helpers import followup


async def handle(sub: str, sub_opts: list, token: str):
    from utils.discord_helpers import opts
    o = opts(sub_opts)

    if sub == "connect":
        pat = o.get("token", "")
        username = o.get("username", "")
        if not pat or not username:
            return await followup(token, "❌ Both `token` and `username` are required.")

        # Verify token works
        import httpx
        try:
            r = httpx.get("https://api.github.com/user",
                          headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
                          timeout=10)
            if r.status_code != 200:
                return await followup(token, f"❌ GitHub token invalid: {r.status_code} {r.text[:200]}")
            real_username = r.json().get("login", username)
        except Exception as e:
            return await followup(token, f"❌ Could not verify token: {e}")

        gh_store.save(pat, real_username)
        await followup(token,
            f"✅ GitHub connected!\n"
            f"**Username:** `{real_username}`\n"
            f"Claude can now create repos, push code, commit, and share GitHub links."
        )

    elif sub == "status":
        t = gh_store.get_token()
        u = gh_store.get_username()
        if not t:
            return await followup(token, "❌ GitHub not connected. Use `/github connect`.")
        await followup(token, f"✅ GitHub connected as **`{u}`**")

    elif sub == "disconnect":
        gh_store.save("", "")
        await followup(token, "✅ GitHub disconnected.")

    else:
        await followup(token, f"❌ Unknown subcommand: `{sub}`")
