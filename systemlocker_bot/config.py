"""Configuration loading and validation for the System Locker Discord bot.

The bot is configured from a single JSON file (``config.json`` by default).
Everything is validated up front with precise error messages so a typo fails
at startup instead of silently disabling a guild hours later.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_CONFIG_PATH = "config.json"
TOKEN_ENV_VARIABLE = "DISCORD_TOKEN"

_SYSTEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{20}$")
_CREDENTIAL_PATTERN = re.compile(r"^slm_[A-Za-z0-9]+_[A-Za-z0-9]+$")

_TIER_NAMES = ("support", "generate", "manage")


class ConfigError(Exception):
    """Raised when the configuration file is missing, malformed, or invalid."""


@dataclass(frozen=True)
class SystemEntry:
    """One System Locker system bound to a Management API v2 credential."""

    name: str
    credential: str
    system_id: str


@dataclass(frozen=True)
class GuildConfig:
    """Per-guild settings: systems, role tiers, admin overrides, log channel."""

    guild_id: int
    systems: Mapping[str, SystemEntry]  # keyed by lowercase name
    tier_roles: Mapping[int, frozenset[int]]  # tier level -> role IDs
    admins: frozenset[int]
    log_channel: int | None

    def system(self, name: str) -> SystemEntry | None:
        return self.systems.get(name.strip().lower())


@dataclass(frozen=True)
class BotConfig:
    token: str | None
    guilds: Mapping[int, GuildConfig]


def load_config(path: str | None = None) -> BotConfig:
    """Read and validate the configuration file at *path*."""
    path = path or os.environ.get("SYSTEMLOCKER_BOT_CONFIG", DEFAULT_CONFIG_PATH)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ConfigError(
            f"Configuration file not found: {path}. "
            "Copy config.example.json to config.json and fill it in."
        ) from None
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from None

    if not isinstance(raw, dict):
        raise ConfigError("The configuration root must be a JSON object.")

    token = _optional_string(raw, "token", path)
    _reject_unknown_keys(raw, {"token", "guilds"}, path)

    guilds_raw = raw.get("guilds")
    if not isinstance(guilds_raw, dict) or not guilds_raw:
        raise ConfigError(f"{path}: 'guilds' must be an object with at least one guild.")

    guilds: dict[int, GuildConfig] = {}
    for guild_key, guild_raw in guilds_raw.items():
        guild_id = _snowflake(guild_key, f"{path}: guild key")
        label = f"{path}: guild {guild_id}"
        if not isinstance(guild_raw, dict):
            raise ConfigError(f"{label} must be an object.")
        guilds[guild_id] = _load_guild(guild_id, guild_raw, label)

    return BotConfig(token=token, guilds=guilds)


def _load_guild(guild_id: int, raw: Mapping[str, Any], label: str) -> GuildConfig:
    _reject_unknown_keys(raw, {"systems", "roles", "admins", "log_channel"}, label)

    systems_raw = raw.get("systems")
    if not isinstance(systems_raw, dict) or not systems_raw:
        raise ConfigError(f"{label}: 'systems' must be an object with at least one system.")

    systems: dict[str, SystemEntry] = {}
    for name, entry_raw in systems_raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{label}: system names must be non-empty strings.")
        entry_label = f"{label}: system '{name}'"
        if not isinstance(entry_raw, dict):
            raise ConfigError(f"{entry_label} must be an object.")
        _reject_unknown_keys(entry_raw, {"credential", "system_id"}, entry_label)

        credential = entry_raw.get("credential")
        if not isinstance(credential, str) or not _CREDENTIAL_PATTERN.match(credential):
            raise ConfigError(
                f"{entry_label}: 'credential' must be a Management API v2 credential "
                "of the form slm_<token_id>_<secret>."
            )
        system_id = entry_raw.get("system_id")
        if not isinstance(system_id, str) or not _SYSTEM_ID_PATTERN.match(system_id):
            raise ConfigError(
                f"{entry_label}: 'system_id' must be the 20-character alphanumeric "
                "system ID from the developer portal."
            )
        key = name.strip().lower()
        if key in systems:
            raise ConfigError(f"{label}: system names must be unique (case-insensitive).")
        systems[key] = SystemEntry(name=name.strip(), credential=credential, system_id=system_id)

    tier_roles: dict[int, frozenset[int]] = {}
    roles_raw = raw.get("roles", {})
    if not isinstance(roles_raw, dict):
        raise ConfigError(f"{label}: 'roles' must be an object.")
    _reject_unknown_keys(roles_raw, set(_TIER_NAMES), f"{label}: roles")
    from .permissions import TIER_BY_NAME

    for tier_name, role_ids in roles_raw.items():
        tier = TIER_BY_NAME[tier_name]
        tier_roles[tier] = frozenset(_snowflake_list(role_ids, f"{label}: roles.{tier_name}"))

    admins = frozenset(_snowflake_list(raw.get("admins", []), f"{label}: admins"))

    log_channel_raw = raw.get("log_channel")
    log_channel: int | None = None
    if log_channel_raw is not None:
        log_channel = _snowflake(log_channel_raw, f"{label}: log_channel")

    return GuildConfig(
        guild_id=guild_id,
        systems=systems,
        tier_roles=tier_roles,
        admins=admins,
        log_channel=log_channel,
    )


def _reject_unknown_keys(raw: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(
            f"{label}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed keys: {', '.join(sorted(allowed))}."
        )


def _optional_string(raw: Mapping[str, Any], key: str, label: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{label}: '{key}' must be a string.")
    return value


def _snowflake(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{label} must be a Discord ID.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ConfigError(f"{label} must be a Discord ID (a number).")


def _snowflake_list(value: Any, label: str) -> list[int]:
    if not isinstance(value, list):
        raise ConfigError(f"{label} must be a list of Discord IDs.")
    return [_snowflake(item, f"{label} entry") for item in value]
