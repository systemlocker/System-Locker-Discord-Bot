"""Role-tier permission model.

Access is organized in three cumulative tiers: ``support`` (read key/system
information, reset a HWID, freeze or unfreeze), ``generate`` (everything
support can do, plus key generation), and ``manage`` (everything, including
destructive actions, variables, pause/resume, and security reads). Configured
admin user IDs and Discord guild administrators always act at ``manage``.
"""

from __future__ import annotations

from typing import Iterable

TIER_NONE = 0
TIER_SUPPORT = 1
TIER_GENERATE = 2
TIER_MANAGE = 3

TIER_BY_NAME = {
    "support": TIER_SUPPORT,
    "generate": TIER_GENERATE,
    "manage": TIER_MANAGE,
}

TIER_NAMES = {TIER_SUPPORT: "support", TIER_GENERATE: "generate", TIER_MANAGE: "manage"}


def effective_tier(
    user_id: int,
    role_ids: Iterable[int],
    tier_roles: dict[int, frozenset[int]],
    admins: Iterable[int] = (),
    *,
    guild_administrator: bool = False,
) -> int:
    """Return the highest tier the user holds in a guild (0 when none)."""
    if guild_administrator or user_id in frozenset(admins):
        return TIER_MANAGE
    held = frozenset(role_ids)
    tier = TIER_NONE
    for level, required_roles in tier_roles.items():
        if held & required_roles:
            tier = max(tier, level)
    return tier


def has_tier(tier: int, required: int) -> bool:
    return tier >= required
