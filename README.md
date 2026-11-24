# System Locker Discord Bot

Official self-hosted Discord bot for staff who support **System Locker**
customers in their own server. Issue licenses, investigate authentication
problems, reset hardware bindings, and manage Nightflyer offline leases
without leaving Discord. It uses **Management API v2**, with role-controlled
commands for variables, resellers, system pauses, and Aegis IP lookups.

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

| Scope            | Used by                                                       |
| ---------------- | ------------------------------------------------------------- |
| `systems.read`   | `/system`, `/stats`, `/nightflyer policy`                     |
| `systems.update` | `/pause`, `/resume`, `/nightflyer update`                     |
| `keys.create`    | `/gen`                                                        |
| `individual_free_trial` | Public `/trial` and configured reaction-based individual trials |
| `keys.read`      | `/key`                                                        |
| `keys.update`    | `/freeze`, `/unfreeze`, `/reset`, `/resetall`, `/addtime`, `/nightflyer unbind` |
| `keys.delete`    | `/deletekey`                                                  |
| `variables.*`    | `/variable …`                                                 |
| `resellers.*`    | `/reseller …` (removing an allowance uses `resellers.delete`) |
| `security.read`  | `/keylogs`, `/iplookup`, `/nightflyer leases`                 |

`/permissions` needs no scope: it shows what the configured credential can do.

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

| Key                         | Required | Meaning                                                                                                                                 |
| --------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `guilds.<id>`               | yes      | One entry per Discord server. Anything else gets "not configured".                                                                      |
| `systems.<name>`            | yes      | A friendly name (used in commands) mapped to a credential and system ID.                                                                |
| `systems.<name>.credential` | yes      | The Management API v2 credential bound to that system.                                                                                  |
| `systems.<name>.system_id`  | yes      | The 20-character system ID from the developer portal.                                                                                   |
| `roles.support`             | no       | Role IDs allowed to inspect keys and offline leases, read stats and policy, reset a HWID, freeze/unfreeze. |
| `roles.generate`            | no       | Role IDs additionally allowed to generate keys.                                                                                         |
| `roles.manage`              | no       | Role IDs additionally allowed to delete keys, add time, reset all HWIDs, pause/resume, change offline policy or revoke leases, manage variables and resellers, and run lookups. |
| `admins`                    | no       | User IDs with full access regardless of roles.                                                                                          |
| `log_channel`               | no       | A channel that receives an embed for every mutation (key generation, deletion, pauses, variable changes).                               |
| `individual_free_trial`     | no       | Configures public individual trials; its `enable` switch remains false until explicitly changed.                                    |

Enable **Developer Mode** in Discord (User Settings → Advanced) to copy IDs
via right-click. Tiers are cumulative — `generate` includes everything
`support` can do, and `manage` includes both. Members with the Discord
**Administrator** permission always act at `manage`.

A credential is bound to exactly one system, so each configured system uses
its own credential. The bot shares one API client per credential and
voluntarily respects the API's rate limit of 10 requests per 5 seconds.

### Individual free trials

Individual free trials are **off unless** a guild has an
`individual_free_trial` block with `"enable": true`. This extra switch
defaults to `false`, so copying a configuration example cannot issue keys.
They use the dedicated
`individual_free_trial` credential scope (not `keys.create`) and always use
the member's Discord ID as the trial identifier, so a member cannot request
another key for that system.

```json
"individual_free_trial": {
  "enable": true,
  "system": "my-product",
  "mode": "command",
  "duration": "7d",
  "notes": "Discord community trial"
}
```

Change `"enable"` to `true` only when you are ready to issue keys. Use
`"mode": "command"` to let members run `/trial`, or use
`"mode": "reaction"` plus a `channel` ID to issue a key when a member adds
the configured emoji (default: `🎉`) to any message in that channel:

```json
"individual_free_trial": {
  "enable": true,
  "system": "my-product",
  "mode": "reaction",
  "channel": 666666666666666666,
  "emoji": "🎉",
  "duration": "7d"
}
```

`duration` is required and starts on first redemption. The key is sent only
by DM and is never mirrored to the guild log channel. Members must permit
DMs from the server before requesting a trial.

## Commands

| Command                                                                     | Tier     | Description                                                           |
| --------------------------------------------------------------------------- | -------- | --------------------------------------------------------------------- |
| `/key system license_key`                                                   | support  | Full details: redemption, claim, HWID, frozen, expiry, notes          |
| `/keylogs system license_key`                                               | support  | The latest five authentication attempts for a key                     |
| `/system system`                                                            | support  | Version, program hash, pause state                                    |
| `/stats system`                                                             | support  | Online and total user counts with computed-at times                   |
| `/systems`                                                                  | support  | Systems configured for this server                                    |
| `/reset system license_key`                                                 | support  | Reset the HWID claimed by a key                                       |
| `/freeze system license_key [compensate]` / `/unfreeze system license_key`  | support  | Freeze or unfreeze a key; `compensate` returns the frozen time to the expiry when unfrozen |
| `/gen system [count] [expiry] [duration] [expires_at] [notes] [free_trial] [format] [reseller]` | generate | Create 1–100 keys, optionally with a custom format or reseller assignment |
| `/trial`                                                                    | —        | Request an opted-in individual free-trial key by DM                  |
| `/addtime system license_key duration`                                      | manage   | Add time to a key's expiry                                            |
| `/deletekey system license_key`                                             | manage   | Permanently delete a key (confirmation prompt)                        |
| `/resetall system`                                                          | manage   | Reset every HWID in the system (confirmation prompt)                  |
| `/pause system`                                                             | manage   | Pause online authentication and end online sessions (confirmation prompt) |
| `/resume system [compensate]`                                               | manage   | Resume; optionally extend key expiries by the paused duration         |
| `/variable get/create/update/delete`                                        | manage   | Manage server-side variables; update accepts an optional `new_name` |
| `/reseller list system` / `/reseller show system token`                     | manage   | List resellers or show one reseller's permissions and allowance       |
| `/reseller create system name …`                                            | manage   | Create a reseller with permissions and an optional allowance          |
| `/reseller permissions system token [flags]`                                | manage   | Replace permissions; omitted flags keep their current value           |
| `/reseller allowance system token type [limits]`                            | manage   | Replace (or disable) a reseller's allowance                           |
| `/reseller allowance-remove system token`                                   | manage   | Remove a reseller's allowance                                         |
| `/reseller reset-password system token`                                     | manage   | Generate a new reseller password (shown once)                         |
| `/reseller delete system token`                                             | manage   | Permanently delete a reseller and its allowance (confirmation prompt) |
| `/iplookup system ip`                                                       | manage   | Aegis manual IP lookup (requires an Aegis plan)                       |
| `/permissions system` | manage | Discover the credential's granted scopes (no API scope required) |
| `/nightflyer policy system` | support | Read offline policy (`systems.read`) |
| `/nightflyer update system [enabled] [max_offline]` | manage | Update offline policy, with confirmation (`systems.update`) |
| `/nightflyer leases system [license_key] [page]` | support | Inspect leases and devices, five per page (`security.read`) |
| `/nightflyer unbind system license_key [authorization_id]` | manage | Revoke one lease, or all active leases for a key when ID is omitted; asks to confirm (`keys.update`) |
| `/help`                                                                     | —        | Command and tier overview                                             |

Staff-command responses are ephemeral — only the invoking staff member sees
them. An individual trial key is instead delivered only by DM to the member
who requested it.
`/gen` previews up to ten keys and attaches a text file when the batch is too
large to show in full. Optional `format` and `reseller` fields use the API's
plan checks: custom formats require an eligible plan, and the reseller must
belong to the selected system. Omitting them uses the API's default key
format and creates keys without a reseller assignment.

A custom format has at least nine `%` placeholders and exactly one `@` or
`!`, with at most 64 characters. Other allowed characters are letters,
numbers, hyphens, and underscores. For example: `@-%%%%-%%%%-%%%%`.

Renaming a variable with `/variable update … new_name:…` also saves the
required `value`. Update software that requests its previous name.

### Nightflyer support

Use `/nightflyer policy` to check whether offline authorization is enabled
and how long a device may stay offline. `/nightflyer update` accepts either
setting or both; `max_offline` is in seconds, from 1,200 (20 minutes) to
7,776,000 (90 days). Omitted settings retain their current values.

For a device or activation problem, run `/nightflyer leases` with the
customer's key. Each record shows its authorization ID, device ID, status,
generation, device assurance and storage mode, last contact, and lease
timing. History includes inactive leases and records whose key was deleted.
Use `page` to continue through results, newest first.

Use `/nightflyer unbind` with an authorization ID to revoke that lease, or
omit the ID to revoke every active lease for the key. The confirmation and
staff log identify the key and selected authorization. `/reset` and
`/resetall` clear online HWID bindings; they do not revoke Nightflyer leases.

**Offline devices cannot receive an immediate revocation.** They can keep
running until their current lease expires and receive policy changes,
pauses, or revocation when they reconnect. Keep this in mind when changing
policy, freezing or deleting a key, pausing a system, or unbinding a lease.

### Durations and dates

`/addtime` and `/gen`'s `duration` accept a unit-suffixed duration —
`90s`, `5m`, `2h`, `7d`, `4w`, `1y` — or a combination like `1d12h`.
Bare numbers are rejected so a typo can never quietly mean seconds.
Fixed expiry dates use `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` (UTC), for
example `2026-09-01` or `2026-09-01 14:30`.

### Resellers

Reseller management requires an active qualifying reseller plan on the
developer account; otherwise these commands fail with a plan error from
the API.

A reseller is created with a name (up to 80 characters), five permission
flags (create, ban, freeze, reset HWID, access all keys), and an optional
allowance. An allowance is either an **overall** total key limit or
**duration** limits per day / week / month / 3 months / year / lifetime —
all six are required for the duration type, and every limit is an integer
from 0 to 4,294,967,295.

`/reseller permissions` replaces the complete permissions object; flags
you leave blank keep their current value instead of silently becoming
`no`.

The reseller **password** is returned only by `/reseller create` and
`/reseller reset-password`, and only in the ephemeral reply to the
invoking staff member — it is never mirrored to the log channel and
cannot be retrieved again later. Reseller tokens are visible to anyone
with the manage tier and appear in the audit log; treat them as
sensitive. Be careful about where you run these commands.

### API client helpers

`ManagementApi` also provides `create_user(username, email, password,
license_keys)` and `add_user_keys(username, password, license_keys)` for
your own integrations with the `users.manage` scope. Each takes 1–100
license keys and returns the server's outcome for every key, so one
unusable key does not hide the others. Registration sends a verification
email. These are deliberately not slash commands: account passwords should
stay out of command options and audit logs.

For integrations that import trials or manage releases, the client also
provides `set_individual_free_trial_identifier(license_key, identifier)`
(`None` clears the identifier), `individual_free_trial_identifier_available`,
and `update_system(version=…, program_hash=…, clear_program_hash=True)`.
Metadata updates need `systems.update`; identifier operations need
`individual_free_trial`. Omitted metadata stays unchanged; clear a hash
with `clear_program_hash=True` alone or alongside a version update.
These helpers have no slash commands. Discord-issued trials always use the
requesting member's ID, and release configuration stays with the developer.

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

| Community bot (v1)                               | This bot                                            |
| ------------------------------------------------ | --------------------------------------------------- |
| `/gen … expire=0–4`                              | `/gen` with expiry presets, durations, or dates     |
| `/checkkey`, `/expiration`                       | `/key` (full details including expiry)              |
| `/users`                                         | `/stats` (online + total, computed-at times)        |
| `/reset`, `/resetall`                            | `/reset`, `/resetall`                               |
| `/deletekey`                                     | `/deletekey` (now with confirmation)                |
| `/adjustexpiry`                                  | `/addtime` (v2 adds time instead of setting it)     |
| local SQLite expiry tracker                      | not needed — v2 reports expiry per key              |
| `/newreseller`, `/listresellers`, `/banreseller` | `/reseller …` (v2 reseller management)              |
| raw-API commands                                 | no equivalent — the bot exposes only typed commands |

## License

Provided as-is for System Locker developers. Feel free to fork and adapt
for your own server, but not for a competing service.
