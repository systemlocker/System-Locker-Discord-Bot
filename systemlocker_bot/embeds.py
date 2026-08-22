"""Consistent embed builders for every response the bot sends."""

from __future__ import annotations

import discord

from . import format as fmt
from .api import (
    ALLOWANCE_OVERALL,
    Allowance,
    IpLookup,
    KeyDetails,
    KeyLogEntry,
    ManagementApiError,
    PauseResult,
    Reseller,
    ResellerPermissions,
    ResellerSummary,
    SystemDetails,
    SystemStatistics,
    Variable,
)

FOOTER_TEXT = "System Locker"

_YES_NO = {True: "Yes", False: "No"}
_CHECK_CROSS = {True: "✅", False: "❌"}


def base(title: str, color: discord.Color, system: str | None = None) -> discord.Embed:
    embed = discord.Embed(title=title, color=color, timestamp=fmt.utc_now())
    footer = f"{FOOTER_TEXT} • {system}" if system else FOOTER_TEXT
    embed.set_footer(text=footer)
    return embed


def error(message: str, *, title: str = "Something went wrong") -> discord.Embed:
    embed = base(title, discord.Color.red())
    embed.description = message
    return embed


def not_configured() -> discord.Embed:
    return error("This server is not configured. Add it to the bot's config file and restart.")


def unknown_system(name: str) -> discord.Embed:
    return error(f"`{name}` is not a configured system in this server.")


def missing_permission(tier_name: str) -> discord.Embed:
    return error(
        f"You need the **{tier_name}** role for this command.",
        title="No permission",
    )


def api_error(error_: ManagementApiError) -> discord.Embed:
    hints = {
        401: "The management credential was rejected. Check that the credential in "
        "the bot's config file is complete and has not been revoked.",
        403: "The bot's credential is missing a scope or plan feature for this "
        "command. Check the scopes listed in the README.",
        404: "Not found — check the system ID, key, or variable name.",
        422: None,
        423: "The developer plan is frozen or expired, so management changes are "
        "blocked until it is active again.",
        429: "The API is rate-limiting this credential. Try again in a few seconds.",
    }
    embed = base("API request failed", discord.Color.red())
    detail = hints.get(error_.status)
    if error_.status >= 500:
        detail = "System Locker returned a server error. Try again shortly."
    if detail is None:
        detail = error_.message or "The request was rejected."
    embed.description = detail
    embed.add_field(name="API code", value=f"`{error_.code}` ({error_.status})", inline=True)
    if error_.message and error_.message != detail:
        embed.add_field(name="API message", value=fmt.shorten(error_.message, 1000), inline=False)
    return embed


def transport_error() -> discord.Embed:
    return error("Could not reach the System Locker API. Check your network and try again.")


# ---------------------------------------------------------------------- systems


def system_details(system_name: str, details: SystemDetails) -> discord.Embed:
    embed = base(f"🖥️ {details.name or system_name}", discord.Color.blue(), system_name)
    embed.add_field(name="System ID", value=f"`{details.id}`", inline=True)
    embed.add_field(name="Version", value=details.version or "—", inline=True)
    embed.add_field(
        name="Paused", value=_YES_NO[details.paused] + (f" {fmt.discord_timestamp(details.paused_at, 'R')}" if details.paused_at else ""), inline=True
    )
    embed.add_field(
        name="Program hash",
        value=f"`{fmt.shorten(details.program_hash, 32)}`" if details.program_hash else "Not set",
        inline=False,
    )
    return embed


def statistics(system_name: str, stats: SystemStatistics) -> discord.Embed:
    embed = base("👥 System statistics", discord.Color.blue(), system_name)
    embed.add_field(
        name="Online now",
        value=f"**{stats.online_users}**\ncomputed {fmt.discord_timestamp(stats.online_computed_at, 'R')}",
        inline=True,
    )
    embed.add_field(
        name="Total users",
        value=f"**{stats.total_users}**\ncomputed {fmt.discord_timestamp(stats.total_users_computed_at, 'R')}",
        inline=True,
    )
    embed.add_field(
        name="Refresh cadence",
        value="Online ≈ every 2 minutes; total hourly.\nA user is an account, or an unredeemed-account key counted once by key.",
        inline=False,
    )
    return embed


def pause_result(system_name: str, result: PauseResult, *, resumed: bool, compensate: bool) -> discord.Embed:
    if resumed:
        embed = base("▶️ System resumed", discord.Color.green(), system_name)
        if compensate and result.compensated_keys:
            embed.description = (
                f"Authentication re-enabled. {result.compensated_keys} key(s) were extended by "
                f"{fmt.format_duration(result.compensated_seconds)} to compensate for the pause."
            )
        else:
            embed.description = "Authentication re-enabled."
    else:
        embed = base("⏸️ System paused", discord.Color.orange(), system_name)
        embed.description = (
            f"Authentication is paused and {result.deleted_sessions} active session(s) were ended. "
            "Use /resume to re-enable."
        )
    return embed


# ------------------------------------------------------------------------ keys


def key_details(system_name: str, key: KeyDetails) -> discord.Embed:
    embed = base("🔑 Key details", discord.Color.blurple(), system_name)
    embed.add_field(name="License key", value=f"`{key.license_key}`", inline=False)
    embed.add_field(name="Redeemed", value=_YES_NO[key.redeemed_at is not None], inline=True)
    embed.add_field(name="Claim", value=key.claim_type or "—", inline=True)
    embed.add_field(name="Username", value=key.username or "—", inline=True)
    embed.add_field(name="HWID set", value=_YES_NO[key.hwid_is_set], inline=True)
    embed.add_field(name="Frozen", value=_CHECK_CROSS[key.frozen], inline=True)
    embed.add_field(name="Free trial", value=_YES_NO[key.free_trial], inline=True)
    embed.add_field(name="Expires", value=fmt.timestamp_line(key.expires_at), inline=False)
    embed.add_field(name="Created", value=fmt.discord_timestamp(key.created_at), inline=True)
    embed.add_field(name="Redeemed at", value=fmt.discord_timestamp(key.redeemed_at), inline=True)
    if key.notes:
        embed.add_field(name="Notes", value=fmt.shorten(key.notes, 1000), inline=False)
    return embed


def key_mutated(title: str, system_name: str, key: KeyDetails) -> discord.Embed:
    embed = base(title, discord.Color.green(), system_name)
    embed.add_field(name="License key", value=f"`{key.license_key}`", inline=True)
    embed.add_field(name="HWID set", value=_YES_NO[key.hwid_is_set], inline=True)
    embed.add_field(name="Frozen", value=_CHECK_CROSS[key.frozen], inline=True)
    embed.add_field(name="Expires", value=fmt.timestamp_line(key.expires_at), inline=False)
    return embed


def keys_generated(
    system_name: str,
    keys: list[str],
    *,
    expiry_label: str,
    notes: str,
    free_trial: bool,
    requested_by: discord.abc.User,
) -> discord.Embed:
    embed = base(f"🔑 {len(keys)} key(s) generated", discord.Color.green(), system_name)
    embed.add_field(name="Expiry", value=expiry_label, inline=True)
    embed.add_field(name="Free trial", value=_YES_NO[free_trial], inline=True)
    embed.add_field(name="Notes", value=fmt.shorten(notes, 500) or "—", inline=True)
    embed.add_field(name="Generated by", value=str(requested_by), inline=True)
    preview = "\n".join(f"`{key}`" for key in keys[:10])
    if len(keys) > 10:
        preview += f"\n… and {len(keys) - 10} more"
    embed.add_field(name="Keys", value=preview, inline=False)
    return embed


def key_deleted(system_name: str, license_key: str) -> discord.Embed:
    embed = base("🚫 Key deleted", discord.Color.red(), system_name)
    embed.description = f"`{fmt.shorten(license_key, 64)}` was permanently deleted."
    return embed


def hwids_reset(system_name: str, count: int) -> discord.Embed:
    embed = base("♻️ HWIDs reset", discord.Color.gold(), system_name)
    embed.description = f"Hardware IDs were cleared for **{count}** key(s)."
    return embed


def key_logs(system_name: str, license_key: str, entries: list[KeyLogEntry]) -> discord.Embed:
    embed = base("🧾 Recent authentication log", discord.Color.dark_grey(), system_name)
    embed.add_field(name="License key", value=f"`{fmt.shorten(license_key, 64)}`", inline=False)
    if not entries:
        embed.description = "No authentication log entries are available for this key."
        return embed
    lines = []
    for entry in entries[:5]:
        when = fmt.discord_timestamp(entry.timestamp, "R")
        who = entry.identity or "unknown"
        if entry.successful:
            lines.append(f"{when} {_CHECK_CROSS[True]} **{who}**")
        else:
            reason = f" — {entry.failure_reason}" if entry.failure_reason else ""
            lines.append(f"{when} {_CHECK_CROSS[False]} **{who}**{reason}")
        details = []
        if entry.hwid:
            details.append(f"hwid `{fmt.shorten(entry.hwid, 24)}`")
        if entry.ip:
            details.append(f"ip `{entry.ip}`")
        if entry.software_version:
            details.append(f"version {entry.software_version}")
        if details:
            lines.append("    " + ", ".join(details))
    embed.description = "\n".join(lines)
    return embed


# ------------------------------------------------------------------- variables


def variable(system_name: str, item: Variable) -> discord.Embed:
    embed = base("🔧 Variable", discord.Color.teal(), system_name)
    embed.add_field(name="Name", value=f"`{item.name}`", inline=True)
    embed.add_field(name="Protected", value=("🔒 Yes" if item.protected else "🔓 No"), inline=True)
    embed.add_field(name="Value", value=f"```\n{fmt.shorten(item.value, 1000) or ' '}\n```", inline=False)
    return embed


def variable_deleted(system_name: str, name: str) -> discord.Embed:
    embed = base("🔧 Variable deleted", discord.Color.red(), system_name)
    embed.description = f"`{name}` was deleted."
    return embed


# ------------------------------------------------------------------- resellers

_RESELLER_COLOR = discord.Color.dark_teal()

_PERMISSION_LABELS = (
    ("Create keys", "can_create_keys"),
    ("Ban keys", "can_ban_keys"),
    ("Freeze keys", "can_freeze_keys"),
    ("Reset HWID", "can_reset_hwid"),
    ("Access all keys", "can_access_all_keys"),
)

_DURATION_LIMIT_LABELS = (
    ("Day", "day_key_limit"),
    ("Week", "week_key_limit"),
    ("Month", "month_key_limit"),
    ("3 months", "month_three_key_limit"),
    ("Year", "year_key_limit"),
    ("Lifetime", "lifetime_key_limit"),
)


def _permissions_field(permissions: ResellerPermissions) -> str:
    return "\n".join(
        f"{_CHECK_CROSS[getattr(permissions, attr)]} {label}" for label, attr in _PERMISSION_LABELS
    )


def _allowance_field(allowance: Allowance | None) -> str:
    if allowance is None:
        return "No allowance is configured."
    if not allowance.enabled:
        return "Disabled."
    if allowance.type == ALLOWANCE_OVERALL:
        return f"Overall key limit: **{allowance.overall_key_limit}**"
    lines = ["Limits per period:"]
    lines += [
        f"{label}: **{getattr(allowance, attr)}**" for label, attr in _DURATION_LIMIT_LABELS
    ]
    return "\n".join(lines)


def reseller_list(system_name: str, summaries: list[ResellerSummary]) -> discord.Embed:
    embed = base("🤝 Resellers", _RESELLER_COLOR, system_name)
    if not summaries:
        embed.description = "No resellers are configured for this system."
        return embed
    lines = [f"`{fmt.shorten(item.token, 64)}` — {item.name}" for item in summaries[:15]]
    if len(summaries) > 15:
        lines.append(f"… and {len(summaries) - 15} more")
    embed.description = "\n".join(lines)
    return embed


def reseller_details(system_name: str, reseller: Reseller) -> discord.Embed:
    embed = base("🤝 Reseller details", _RESELLER_COLOR, system_name)
    embed.add_field(name="Name", value=fmt.shorten(reseller.name, 200) or "—", inline=True)
    embed.add_field(name="Token", value=f"`{fmt.shorten(reseller.token, 64)}`", inline=True)
    embed.add_field(name="Permissions", value=_permissions_field(reseller.permissions), inline=False)
    embed.add_field(
        name="Allowance",
        value=_allowance_field(reseller.allowance),
        inline=False,
    )
    return embed


def reseller_created(
    system_name: str, reseller: Reseller, *, password: str | None = None
) -> discord.Embed:
    embed = base("🤝 Reseller created", discord.Color.green(), system_name)
    if password is not None:
        embed.description = (
            "The reseller's password is shown **only here** — copy it now; it "
            "cannot be retrieved later and is not mirrored to the log channel."
        )
    embed.add_field(name="Name", value=fmt.shorten(reseller.name, 200) or "—", inline=True)
    embed.add_field(name="Token", value=f"`{fmt.shorten(reseller.token, 64)}`", inline=True)
    if password is not None:
        embed.add_field(name="Password", value=f"`{password}`", inline=True)
    embed.add_field(name="Permissions", value=_permissions_field(reseller.permissions), inline=False)
    embed.add_field(name="Allowance", value=_allowance_field(reseller.allowance), inline=False)
    return embed


def reseller_permissions(
    system_name: str, token: str, permissions: ResellerPermissions
) -> discord.Embed:
    embed = base("🛠️ Reseller permissions", _RESELLER_COLOR, system_name)
    embed.add_field(name="Token", value=f"`{fmt.shorten(token, 64)}`", inline=False)
    embed.add_field(name="Permissions", value=_permissions_field(permissions), inline=False)
    return embed


def reseller_allowance(system_name: str, token: str, allowance: Allowance | None) -> discord.Embed:
    embed = base("🧮 Reseller allowance", _RESELLER_COLOR, system_name)
    embed.add_field(name="Token", value=f"`{fmt.shorten(token, 64)}`", inline=False)
    embed.add_field(name="Allowance", value=_allowance_field(allowance), inline=False)
    return embed


def reseller_allowance_removed(system_name: str, token: str) -> discord.Embed:
    embed = base("🧮 Allowance removed", discord.Color.red(), system_name)
    embed.description = f"The allowance for `{fmt.shorten(token, 64)}` was removed."
    return embed


def reseller_password_reset(
    system_name: str, token: str, *, password: str | None = None
) -> discord.Embed:
    embed = base("🔁 Reseller password reset", discord.Color.green(), system_name)
    if password is not None:
        embed.description = (
            "The new password is shown **only here** — copy it now; it cannot "
            "be retrieved later and is not mirrored to the log channel."
        )
        embed.add_field(name="Token", value=f"`{fmt.shorten(token, 64)}`", inline=True)
        embed.add_field(name="New password", value=f"`{password}`", inline=True)
    else:
        embed.description = f"A new password was generated for `{fmt.shorten(token, 64)}`."
    return embed


def reseller_deleted(system_name: str, token: str) -> discord.Embed:
    embed = base("🤝 Reseller deleted", discord.Color.red(), system_name)
    embed.description = (
        f"Reseller `{fmt.shorten(token, 64)}` and its allowance were permanently deleted."
    )
    return embed


# -------------------------------------------------------------------- security


def ip_lookup(system_name: str, lookup: IpLookup) -> discord.Embed:
    embed = base("🛡️ IP lookup", discord.Color.dark_blue(), system_name)
    embed.add_field(name="IP", value=f"`{lookup.ip}`", inline=True)
    embed.add_field(name="Country", value=lookup.country or "—", inline=True)
    embed.add_field(name="Possible VPN", value=_YES_NO.get(lookup.possible_vpn, "—"), inline=True)
    embed.add_field(name="ASN", value=str(lookup.asn) if lookup.asn else "—", inline=True)
    embed.add_field(name="AS name", value=fmt.shorten(lookup.as_name, 200) or "—", inline=True)
    embed.add_field(name="Provider type", value=lookup.provider_type or "—", inline=True)
    if lookup.location:
        embed.add_field(name="Location", value=fmt.shorten(lookup.location, 200), inline=False)
    return embed
