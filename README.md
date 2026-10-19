# MyFitnessPal MCP for macOS — restricted session edition

A local stdio MCP server for Claude Desktop. All diary, measurement, goals,
water, steps, custom-food and fasting tools remain available, including writes
and deletes. Authentication has deliberately changed from the original project.

## Security boundaries

- No automatic browser discovery, browser cookie database reads, Safe Storage
  key lookups, username/password login, or plaintext cookie-file fallback.
- Only manually supplied MyFitnessPal session cookies are accepted. They are
  stored in the native macOS Keychain under service `mfp-mcp-session`, account
  `myfitnesspal`. An unavailable/denied Keychain causes an error; no fallback.
- No session secrets in Claude configuration, command arguments or MCP tools.
  The standalone Terminal importer uses hidden input and refuses echoed input.
- The HTTP transport permits only HTTPS on port 443 to
  `www.myfitnesspal.com` and `api.myfitnesspal.com`. Every redirect is checked.
  TLS verification is mandatory. Environment proxies, `.netrc` authentication
  and environment CA overrides are ignored; explicit proxies are rejected.
- Imported session cookies are sent only to `www.myfitnesspal.com`. The API
  uses the bearer token returned by MyFitnessPal. Response error bodies and
  raw exception messages are withheld from tool errors.
- No listening HTTP server: the entry point explicitly uses stdio.
- `uv.lock` records exact transitive dependency versions and artifact hashes.
  `myfitnesspal` is pinned because our restricted initializer replaces its
  browser-discovering constructor. Its `browser-cookie3` and `cloudscraper`
  dependencies are still installed/imported, but their authentication paths
  are not called. Regression tests enforce this.

These are application controls, **not an OS sandbox or a zero-leak guarantee**.
A compromised dependency or process running with your permissions could bypass
Python-level controls. Keychain does not protect against every program running
as you. Locking dependencies makes installs repeatable; it does not prove those
packages are vulnerability-free. Use a dedicated macOS user/VM if other browser
accounts must be outside the process's filesystem permissions. An external
firewall policy can additionally restrict that user's/process's network egress.

MCP results intentionally include your food diary and health data. They are
passed to Claude Desktop and may be processed by the model provider. Local MCP
does not make Claude inference local. Review your account's data/privacy
settings. Never paste session cookies into Claude. Writes and deletes execute
when the MCP client invokes them; client-side approval settings matter.
`public=true` on custom-food creation intentionally publishes that food to
MyFitnessPal's shared database; leave it false for private foods.

## Features

| Tool | Type | Description |
|------|------|-------------|
| `mfp_get_diary` | Read | Get food diary entries for any date |
| `mfp_search_food` | Read | Search the MyFitnessPal food database |
| `mfp_get_food_details` | Read | Get detailed nutrition info for a food item |
| `mfp_add_food_to_diary` | Write | Add a food item to your diary for a specific meal and date |
| `mfp_remove_food_from_diary` | Write | Remove a logged entry from your diary |
| `mfp_create_custom_food` | Write | Create a private custom food with a full nutrition panel |
| `mfp_list_own_foods` | Read | List your own custom foods (private ones do not appear in search) |
| `mfp_delete_custom_food` | Write | Delete one of your custom foods |
| `mfp_get_measurements` | Read | Get weight/body measurement history |
| `mfp_set_measurement` | Write | Log a new weight or body measurement |
| `mfp_get_exercises` | Read | Get logged exercises (cardio & strength) |
| `mfp_get_goals` | Read | Get daily nutrition goals |
| `mfp_set_goals` | Write | Update daily nutrition goals |
| `mfp_get_water` | Read | Get water intake for a date |
| `mfp_set_water` | Write | Log water intake for a date |
| `mfp_get_steps` | Read | Get daily step counts synced from Apple Health / devices |
| `mfp_log_fast` | Write | Log a completed intermittent fasting window (start + end) |
| `mfp_update_fast` | Write | Update the start/end times of an existing fasting entry |
| `mfp_delete_fast` | Write | Delete a fasting entry by id |
| `mfp_get_report` | Read | Get nutrition reports over a date range |


## Install on your MacBook

Install Python 3.12 and uv using their official installers, then copy/clone this
reviewed checkout to a local directory. Do not install the original PyPI package
in its place: these protections belong to this checkout.

```sh
cd /absolute/path/to/myfitnesspal-mcp-python
uv sync --locked --python 3.12
```

Do not use an unlocked `pip install -e .` for deployment. Do not run package
updates from Claude startup. Review dependency changes before regenerating the
lock. The supported runtime is Python 3.10–3.12; 3.12 is recommended on macOS.

## Import your MyFitnessPal session once

1. Sign into `https://www.myfitnesspal.com` yourself in your browser.
2. Open the browser's developer tools, then its Cookies/Storage panel for that
   exact site. Find the actual session cookie(s): usually
   `__Secure-next-auth.session-token`, or `_mfp_session`. Chunked names such as
   `__Secure-next-auth.session-token.0` and `.1` are accepted; include every
   chunk with its original name. CSRF and unrelated cookies are not needed.
3. In **Terminal**, run:

```sh
/absolute/path/to/myfitnesspal-mcp-python/.venv/bin/mfp-session import
```

At the hidden prompt, paste a JSON object using the actual cookie name and value:

```json
{"__Secure-next-auth.session-token":"YOUR_SESSION_VALUE"}
```

Enter the JSON at the prompt, **not in a shell command or Claude chat**. Do not
export your entire cookie store or use an online cookie conversion tool. Clear
the clipboard after pasting. Keychain may ask permission for your Python
executable to access this project's own session item. The application never
needs access to Chrome/Arc/other browsers' Safe Storage items.

The importer only stores and validates the shape; it does not make a live login
request. Your first MCP request verifies whether MyFitnessPal accepts the session.
If authentication expires, import a fresh session in Terminal. Stored sessions
older than 30 days are refused; this local limit does not revoke them on MFP.

## Claude Desktop configuration

Merge the following server entry into your existing
`~/Library/Application Support/Claude/claude_desktop_config.json`, replacing
`YOUR_NAME` and the project path with your real absolute paths:

```json
{
  "mcpServers": {
    "myfitnesspal": {
      "command": "/Users/YOUR_NAME/path/to/myfitnesspal-mcp-python/.venv/bin/mfp-mcp"
    }
  }
}
```

No `env` credentials or `uv run` startup download is needed. Restart Claude
Desktop after saving. Start with a diary read for today, then verify one write
that you explicitly want. Keep destructive-tool approvals enabled in the client
where supported. The server retains all write/delete tools.

## Existing installations and revocation

Old `~/.mfp_mcp/cookies.json` files and old `MFP_USERNAME`, `MFP_PASSWORD`,
`MFP_SECRET_KEY` settings are ignored, not automatically deleted. After confirming
the new setup works, remove obsolete plaintext cookie files/config secrets and
unneeded backups yourself. Review any old browser Safe Storage Keychain grants.

To remove only this application's stored session:

```sh
/absolute/path/to/myfitnesspal-mcp-python/.venv/bin/mfp-session delete
```

Deleting a local Keychain item does not revoke an already copied session or
Claude conversation content. Use MyFitnessPal's session/account controls to
invalidate exposed sessions where available; a password change's effect on
existing sessions must not be assumed.

## Verification

```sh
uv sync --locked --extra dev --python 3.12
uv run --locked --extra dev pytest -q
```

Tests use fake HTTP responses and fake sessions; no live MyFitnessPal account is
required. On macOS, one additional test writes and deletes a uniquely named dummy
Keychain item to verify the native backend. It does not access your real session.
CI runs on Linux and macOS. Live MFP writes and Claude Desktop integration still
need a deliberate smoke test on your MacBook; Windows tests do not establish that
the macOS Keychain permissions work on your machine.

MyFitnessPal's private web/API endpoints can change without notice. A blocked
redirect or unexpected login flow fails closed; review it before expanding the
host allowlist. Docker/browser-profile mounts and the original encrypted-password
setup are not supported by this edition.
