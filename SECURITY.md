# Security notes

## Threat model

This bot is a **server-side management tool**. It authenticates to the
System Locker Management API v2 with a bearer credential and exposes the
resulting capabilities to selected Discord roles. Two secrets are involved:

1. **The Discord bot token** — full control of the bot user.
2. **The management credential** (`slm_…`) — control of one System Locker
   system, limited only by the scopes selected when it was created.

Both belong only on infrastructure you control. Never commit them, never
paste them into chat, never embed them in copies of this bot you distribute.

## Credential handling

- Create the credential with the **least scopes** the commands you use
  require (see the README's scope table). `systems.delete` is never used by
  this bot — leave it unselected.
- A credential is shown once at creation. If it may have been exposed
  (leaked config, screenshot, ex-employee), **revoke it** in the developer
  portal and issue a new one.
- The bot sends the credential only to `https://systemlocker.net` as an
  `Authorization: Bearer` header over TLS. It is never logged and never
  included in Discord messages.
- `config.json` is gitignored; `config.example.json` contains placeholders
  only. Prefer the `DISCORD_TOKEN` environment variable for the bot token.

## What the bot deliberately does not do

- It cannot delete a system — the command does not exist, and a credential
  without `systems.delete` cannot be talked into it.
- It offers no raw "run any API call" passthrough; only the documented
  commands exist.
- Destructive actions (`/deletekey`, `/resetall`, `/pause`) require an
  explicit confirmation click from the invoking staff member.

## Access control

Permission checks are role-based per server, evaluated on every
interaction: members need a role listed under the command's tier (or the
Discord Administrator permission, or listing in `admins`). All responses
are ephemeral, so key material is never left visible in a public channel.
Autocomplete and error messages reveal only the system names you configured.

## Sensitive data the bot produces

- `logs/audit.log` records every command with its arguments — including
  license keys, and usernames/IP addresses when `/keylogs` or `/iplookup`
  are used. Restrict host access accordingly.
- The configured `log_channel` receives key-generation and other mutation
  embeds. Make it staff-only.
- `/keylogs` shows IP addresses only to the extent the developer's logging
  level permits, and `/iplookup` requires the Aegis plan.

## Rate limiting

The API allows 10 requests per 5 seconds per credential. The bot enforces
the same limit client-side per credential and honours server `Retry-After`
on HTTP 429 with one retry; sustained parallel use by many staff can still
queue briefly.

## Reporting

Report vulnerabilities privately through the System Locker support
channels, not via public issues.
