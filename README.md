# System Locker Discord Bot

Official self-hosted Discord bot for the **System Locker Management API v2**.
Generate and manage license keys, read system statistics, manage server-side
variables, and run Aegis IP lookups — from slash commands in your own server.

The bot is a server-side tool: it holds a management credential and speaks
only to `https://systemlocker.net`. It is intended for the staff of one
developer account, configured per Discord server.

## Requirements

- Python 3.10 or newer
- A [Discord application](https://discord.com/developers/applications) with a bot user
- A **Management API v2** credential from the System Locker developer portal
  (Systems page → select a system → create credential)

## Setup

### 1. Create the Discord bot

Create an application in the Discord developer portal and add a bot user.
Invite it to your server with both the `bot` and `applications.commands`
scopes. The bot needs no privileged intents — standard permissions are
`View Channels`, `Send Messages`, `Embed Links`, and `Attach Files`.

### 2. Create a management credential

In the System Locker developer portal, open the **Systems** page, select a
system, and create a Management API v2 credential. Its complete value
(`slm_<token_id>_<secret>`) is shown once — copy it immediately.

Pick the **least scopes the bot needs** for the commands you plan to use:

| Scope            | Used by                                                   |
| ---------------- | --------------------------------------------------------- |
| `systems.read`   | `/system`, `/stats`                                       |
| `systems.update` | `/pause`, `/resume`                                       |
| `keys.create`    | `/gen`                                                    |
| `keys.read`      | `/key`                                                    |
| `keys.update`    | `/freeze`, `/unfreeze`, `/reset`, `/resetall`, `/addtime` |
| `keys.delete`    | `/deletekey`                                              |
| `variables.*`    | `/variable …`                                             |
| `security.read`  | `/keylogs`, `/iplookup`                                   |

`systems.delete` is never used by this bot — leave it out.

### 3. Configure and run

```sh
cp config.example.json config.json   # then edit it
pip install -r requirements.txt
python main.py
```

Provide the Discord token either as the `DISCORD_TOKEN` environment
variable (recommended) or in the `token` field of the configuration file.

Commands appear immediately in every server listed in the configuration.
Pass `--sync-global` once if you also want them available in servers that
are not configured (new servers still need a configuration entry before
commands work).

## Configuration reference

The configuration file maps Discord servers to systems and roles. Structure:

```json
{
	"token": "…optional, DISCORD_TOKEN preferred…",
	"guilds": {
		"<guild id>": {
			"systems": { "<name>": { "credential": "slm_…", "system_id": "…" } },
			"roles": { "support": [], "generate": [], "manage": [] },
			"admins": [],
			"log_channel": null
		}
	}
}
```

| Key                         | Required | Meaning                                                                                                                   |
| --------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------- |
| `guilds.<id>`               | yes      | One entry per Discord server. Anything else gets "not configured".                                                        |
| `systems.<name>`            | yes      | A friendly name (used in commands) mapped to a credential and system ID.                                                  |
| `systems.<name>.credential` | yes      | The Management API v2 credential bound to that system.                                                                    |
| `systems.<name>.system_id`  | yes      | The 20-character system ID from the developer portal.                                                                     |
| `roles.support`             | no       | Role IDs allowed to inspect keys, read stats, reset a HWID, freeze/unfreeze.                                              |
| `roles.generate`            | no       | Role IDs additionally allowed to generate keys.                                                                           |
| `roles.manage`              | no       | Role IDs additionally allowed to delete keys, add time, reset all HWIDs, pause/resume, manage variables, and run lookups. |
| `admins`                    | no       | User IDs with full access regardless of roles.                                                                            |
| `log_channel`               | no       | A channel that receives an embed for every mutation (key generation, deletion, pauses, variable changes).                 |

Enable **Developer Mode** in Discord (User Settings → Advanced) to copy IDs
via right-click. Tiers are cumulative — `generate` includes everything
`support` can do, and `manage` includes both. Members with the Discord
**Administrator** permission always act at `manage`.

A credential is bound to exactly one system, so each configured system uses
its own credential. The bot shares one API client per credential and
voluntarily respects the API's rate limit of 10 requests per 5 seconds.

## Commands

| Command                                                                     | Tier     | Description                                                   |
| --------------------------------------------------------------------------- | -------- | ------------------------------------------------------------- |
| `/key system license_key`                                                   | support  | Full details: redemption, claim, HWID, frozen, expiry, notes  |
| `/keylogs system license_key`                                               | support  | The latest five authentication attempts for a key             |
| `/system system`                                                            | support  | Version, program hash, pause state                            |
| `/stats system`                                                             | support  | Online and total user counts with computed-at times           |
| `/systems`                                                                  | support  | Systems configured for this server                            |
| `/reset system license_key`                                                 | support  | Reset the HWID claimed by a key                               |
| `/freeze` / `/unfreeze system license_key`                                  | support  | Freeze or unfreeze a key                                      |
| `/gen system [count] [expiry] [duration] [expires_at] [notes] [free_trial]` | generate | Create 1–100 keys                                             |
| `/addtime system license_key duration`                                      | manage   | Add time to a key's expiry                                    |
| `/deletekey system license_key`                                             | manage   | Permanently delete a key (confirmation prompt)                |
| `/resetall system`                                                          | manage   | Reset every HWID in the system (confirmation prompt)          |
| `/pause system`                                                             | manage   | Pause authentication and end sessions (confirmation prompt)   |
| `/resume system [compensate]`                                               | manage   | Resume; optionally extend key expiries by the paused duration |
| `/variable get/create/update/delete`                                        | manage   | Manage server-side variables                                  |
| `/iplookup system ip`                                                       | manage   | Aegis manual IP lookup (requires an Aegis plan)               |
| `/help`                                                                     | —        | Command and tier overview                                     |

All responses are ephemeral — only the invoking staff member sees them.
`/gen` shows the first ten keys in the response and attaches a text file
when more are created.

### Durations and dates

`/addtime` and `/gen`'s `duration` accept a unit-suffixed duration —
`90s`, `5m`, `2h`, `7d`, `4w`, `1y` — or a combination like `1d12h`.
Bare numbers are rejected so a typo can never quietly mean seconds.
Fixed expiry dates use `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` (UTC), for
example `2026-09-01` or `2026-09-01 14:30`.

## Logs

The bot writes to the console and keeps an append-only audit trail in
`logs/audit.log` (rotated at 2 MB) recording every command invocation with
its arguments. If `log_channel` is set, mutations are also mirrored there
as embeds. Both contain key material and, with `/keylogs` and `/iplookup`,
usernames and IP addresses — treat them as sensitive.

## Security

See [SECURITY.md](SECURITY.md). In short: the configuration file holds
live credentials and must never be committed or shared; create the
credential with the least scopes the bot needs; revoke it immediately if it
may have been exposed.

## Migrating from the community v1 bot

The earlier community bot targeted the legacy v1 API, which is being
retired. This bot covers the same workflow with v2:

| Community bot (v1)            | This bot                                        |
| ----------------------------- | ----------------------------------------------- |
| `/gen … expire=0–4`           | `/gen` with expiry presets, durations, or dates |
| `/checkkey`, `/expiration`    | `/key` (full details including expiry)          |
| `/users`                      | `/stats` (online + total, computed-at times)    |
| `/reset`, `/resetall`         | `/reset`, `/resetall`                           |
| `/deletekey`                  | `/deletekey` (now with confirmation)            |
| `/adjustexpiry`               | `/addtime` (v2 adds time instead of setting it) |
| local SQLite expiry tracker   | not needed — v2 reports expiry per key          |
| reseller and raw-API commands | no v2 equivalent; removed                       |

## License

Provided as-is for System Locker developers. Feel free to fork and adapt
for your own server, but not for a competing service.
