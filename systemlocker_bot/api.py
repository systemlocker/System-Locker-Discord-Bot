"""Async client for the System Locker Management API v2.

Each instance is bound to one credential (and therefore one system, since a
v2 credential always belongs to exactly one system). The HTTP layer is
injectable so the client can be exercised without a network; the default
transport uses aiohttp, which discord.py already depends on.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from urllib.parse import quote

DEFAULT_BASE_URL = "https://systemlocker.net/api/v2"
DEFAULT_TIMEOUT_SECONDS = 15.0
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 5.0

USER_AGENT = "systemlocker-discord-bot/1.0"


class ManagementApiError(Exception):
    """An error response from the Management API.

    ``status`` is the HTTP status code, ``code`` the API error code (for
    example ``INSUFFICIENT_SCOPE``), and ``message`` the human-readable text.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class ApiTransportError(Exception):
    """The API could not be reached, or returned something undecodable."""


@dataclass
class Expiry:
    """Base for the three key-expiry modes of the create-keys endpoint."""

    def to_body(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class Perpetual(Expiry):
    def to_body(self) -> dict[str, Any]:
        return {"type": "perpetual"}


@dataclass
class AfterRedemption(Expiry):
    seconds: int

    def __post_init__(self) -> None:
        if self.seconds <= 0:
            raise ValueError("after-redemption seconds must be positive.")

    def to_body(self) -> dict[str, Any]:
        return {"type": "after_redemption", "seconds": self.seconds}


@dataclass
class ExpiresAt(Expiry):
    at: datetime

    def to_body(self) -> dict[str, Any]:
        return {"type": "at", "at": format_timestamp(self.at)}


@dataclass(frozen=True)
class SystemDetails:
    id: str
    name: str
    version: str | None
    program_hash: str | None
    paused: bool
    paused_at: datetime | None


@dataclass(frozen=True)
class SystemStatistics:
    online_users: int
    online_computed_at: datetime | None
    total_users: int
    total_users_computed_at: datetime | None


@dataclass(frozen=True)
class PauseResult:
    system_id: str
    paused: bool
    paused_at: datetime | None
    deleted_sessions: int
    compensated_keys: int
    compensated_seconds: int


@dataclass(frozen=True)
class KeyDetails:
    license_key: str
    claim_type: str | None
    username: str | None
    hwid_is_set: bool
    frozen: bool
    free_trial: bool
    notes: str | None
    expires_at: datetime | None
    created_at: datetime | None
    redeemed_at: datetime | None


@dataclass(frozen=True)
class Variable:
    name: str
    value: str
    protected: bool


ALLOWANCE_OVERALL = "overall"
ALLOWANCE_DURATION = "duration"

KEY_LIMIT_MIN = 0
KEY_LIMIT_MAX = 4_294_967_295

_DURATION_LIMIT_FIELDS = (
    "day_key_limit",
    "week_key_limit",
    "month_key_limit",
    "month_three_key_limit",
    "year_key_limit",
    "lifetime_key_limit",
)

RESELLER_NAME_MAX = 80


@dataclass
class ResellerPermissions:
    """The five reseller capability flags, always sent as one complete object."""

    can_create_keys: bool = False
    can_ban_keys: bool = False
    can_freeze_keys: bool = False
    can_reset_hwid: bool = False
    can_access_all_keys: bool = False

    def to_body(self) -> dict[str, bool]:
        return {
            "can_create_keys": self.can_create_keys,
            "can_ban_keys": self.can_ban_keys,
            "can_freeze_keys": self.can_freeze_keys,
            "can_reset_hwid": self.can_reset_hwid,
            "can_access_all_keys": self.can_access_all_keys,
        }

    @classmethod
    def from_body(cls, data: Mapping[str, Any]) -> "ResellerPermissions":
        return cls(
            can_create_keys=bool(data.get("can_create_keys")),
            can_ban_keys=bool(data.get("can_ban_keys")),
            can_freeze_keys=bool(data.get("can_freeze_keys")),
            can_reset_hwid=bool(data.get("can_reset_hwid")),
            can_access_all_keys=bool(data.get("can_access_all_keys")),
        )


@dataclass
class Allowance:
    """A reseller's key allowance; ``enabled=False`` means none is configured.

    When enabled, ``type`` is ``overall`` with ``overall_key_limit``, or
    ``duration`` with all six duration limits. Completeness and type are
    validated when the outgoing body is built, so partially-filled objects
    returned by the API still parse.
    """

    enabled: bool
    type: str | None = None
    overall_key_limit: int | None = None
    day_key_limit: int | None = None
    week_key_limit: int | None = None
    month_key_limit: int | None = None
    month_three_key_limit: int | None = None
    year_key_limit: int | None = None
    lifetime_key_limit: int | None = None

    def __post_init__(self) -> None:
        for field in ("overall_key_limit",) + _DURATION_LIMIT_FIELDS:
            value = getattr(self, field)
            if value is not None and not KEY_LIMIT_MIN <= value <= KEY_LIMIT_MAX:
                raise ValueError(f"{field} must be between {KEY_LIMIT_MIN} and {KEY_LIMIT_MAX}.")

    def to_body(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        if self.type == ALLOWANCE_OVERALL:
            if self.overall_key_limit is None:
                raise ValueError("an overall allowance needs overall_key_limit.")
            return {
                "enabled": True,
                "type": self.type,
                "overall_key_limit": self.overall_key_limit,
            }
        if self.type == ALLOWANCE_DURATION:
            missing = [field for field in _DURATION_LIMIT_FIELDS if getattr(self, field) is None]
            if missing:
                raise ValueError(
                    "a duration allowance needs all six limits: " + ", ".join(missing) + "."
                )
            body: dict[str, Any] = {"enabled": True, "type": self.type}
            for field in _DURATION_LIMIT_FIELDS:
                body[field] = getattr(self, field)
            return body
        raise ValueError("allowance type must be 'overall' or 'duration'.")

    @classmethod
    def from_body(cls, data: Mapping[str, Any]) -> "Allowance":
        return cls(
            enabled=bool(data.get("enabled", data.get("type") is not None)),
            type=data.get("type"),
            overall_key_limit=_optional_int(data.get("overall_key_limit")),
            day_key_limit=_optional_int(data.get("day_key_limit")),
            week_key_limit=_optional_int(data.get("week_key_limit")),
            month_key_limit=_optional_int(data.get("month_key_limit")),
            month_three_key_limit=_optional_int(data.get("month_three_key_limit")),
            year_key_limit=_optional_int(data.get("year_key_limit")),
            lifetime_key_limit=_optional_int(data.get("lifetime_key_limit")),
        )


@dataclass(frozen=True)
class ResellerSummary:
    token: str
    name: str


@dataclass(frozen=True)
class Reseller:
    token: str
    name: str
    permissions: ResellerPermissions
    allowance: Allowance | None
    password: str | None = None  # only ever present in create / password-reset replies


@dataclass(frozen=True)
class IpLookup:
    ip: str
    asn: str | None
    as_name: str | None
    country: str | None
    location: str | None
    possible_vpn: bool | None
    provider_type: str | None


@dataclass(frozen=True)
class KeyLogEntry:
    identity: str | None
    hwid: str | None
    software_version: str | None
    successful: bool
    failure_reason: str | None
    ip: str | None
    timestamp: datetime | None


class TransportResponse:
    def __init__(self, status: int, headers: Mapping[str, str], text: str) -> None:
        self.status = status
        self.headers = headers
        self.text = text


class Transport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None = None,
        json_body: Any | None = None,
    ) -> TransportResponse: ...


class AiohttpTransport:
    """Default transport over a shared aiohttp session.

    The aiohttp import is deferred so the rest of this module can be used and
    exercised without the HTTP stack present.
    """

    def __init__(self, session: Any, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        import aiohttp

        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None = None,
        json_body: Any | None = None,
    ) -> TransportResponse:
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=self._timeout,
            ) as response:
                return TransportResponse(response.status, response.headers, await response.text())
        except asyncio.CancelledError:
            raise
        except Exception as error:  # aiohttp errors, timeouts, DNS, TLS…
            raise ApiTransportError(f"Could not reach the System Locker API: {error}") from error


class SlidingWindowRateLimiter:
    """Client-side companion to the API's 10-requests-per-5-seconds limit."""

    def __init__(self, max_events: int, window: float) -> None:
        self._max_events = max_events
        self._window = window
        self._events: list[float] = []

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            self._events = [stamp for stamp in self._events if now - stamp < self._window]
            if len(self._events) < self._max_events:
                self._events.append(now)
                return
            await asyncio.sleep(self._window - (now - self._events[0]) + 0.01)


_TIMESTAMP_FRACTION = re.compile(r"\.(\d{7,})")
_TIMESTAMP_OFFSET = re.compile(r"([+-]\d{2})(\d{2})$")
_TIMESTAMP_SPACE = re.compile(r"^(\d{4}-\d{2}-\d{2}) ")


def parse_timestamp(value: Any) -> datetime | None:
    """Parse the timestamp shapes the API emits or accepts into aware UTC.

    Accepts RFC 3339 strings (``Z``, ``+00:00``, ``+0000``, fractional
    seconds, a space separator) and raw Unix seconds.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)

    text = _TIMESTAMP_FRACTION.sub(lambda m: "." + m.group(1)[:6], text)
    text = _TIMESTAMP_SPACE.sub(r"\1T", text)
    text = _TIMESTAMP_OFFSET.sub(r"\1:\2", text)
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    """Render a datetime as RFC 3339 UTC with second precision."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ManagementApi:
    """One credential's view of the Management API v2 for its bound system."""

    def __init__(
        self,
        credential: str,
        system_id: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: Transport,
        rate_limit_requests: int = RATE_LIMIT_REQUESTS,
        rate_limit_window: float = RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._credential = credential
        self._system_id = system_id
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._headers = {
            "Authorization": f"Bearer {credential}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self._limiter = SlidingWindowRateLimiter(rate_limit_requests, rate_limit_window)

    @property
    def system_id(self) -> str:
        return self._system_id

    # ------------------------------------------------------------------ systems

    async def list_systems(self) -> list[SystemDetails]:
        data = await self._request("GET", "/systems")
        return [self._system_details(item) for item in _as_list(data)]

    async def get_system(self) -> SystemDetails:
        return self._system_details(await self._request("GET", self._system_path()))

    async def get_statistics(self) -> SystemStatistics:
        data = await self._request("GET", f"{self._system_path()}/statistics")
        return SystemStatistics(
            online_users=int(data.get("online_users") or 0),
            online_computed_at=parse_timestamp(data.get("online_computed_at")),
            total_users=int(data.get("total_users") or 0),
            total_users_computed_at=parse_timestamp(data.get("total_users_computed_at")),
        )

    async def pause_system(self) -> PauseResult:
        return self._pause_result(await self._request("PUT", f"{self._system_path()}/pause"))

    async def resume_system(self, compensate: bool = False) -> PauseResult:
        body = {"compensate": compensate} if compensate else None
        return self._pause_result(await self._request("DELETE", f"{self._system_path()}/pause", json_body=body))

    # --------------------------------------------------------------------- keys

    async def create_keys(
        self,
        count: int,
        *,
        expiry: Expiry | None = None,
        notes: str | None = None,
        free_trial: bool = False,
    ) -> list[str]:
        if not 1 <= count <= 100:
            raise ValueError("count must be between 1 and 100.")
        body: dict[str, Any] = {"count": count}
        body["expiry"] = (expiry or Perpetual()).to_body()
        if notes is not None:
            body["notes"] = notes
        body["free_trial"] = free_trial
        data = await self._request("POST", f"{self._system_path()}/keys", json_body=body)
        keys = _as_list(data.get("keys")) if isinstance(data, dict) else _as_list(data)
        return [str(key) for key in keys]

    async def get_key(self, license_key: str) -> KeyDetails:
        return self._key_details(await self._request("GET", self._key_path(license_key)))

    async def set_frozen(self, license_key: str, frozen: bool) -> KeyDetails:
        data = await self._request(
            "PATCH", self._key_path(license_key), json_body={"frozen": frozen}
        )
        return self._key_details(data)

    async def reset_hwid(self, license_key: str) -> KeyDetails:
        return self._key_details(
            await self._request("POST", f"{self._key_path(license_key)}/hwid-reset")
        )

    async def reset_all_hwids(self) -> int:
        data = await self._request("POST", f"{self._system_path()}/keys/hwid-reset")
        return int(data.get("updated") or 0) if isinstance(data, dict) else 0

    async def add_time(self, license_key: str, seconds: int) -> KeyDetails:
        if seconds <= 0:
            raise ValueError("seconds must be positive.")
        data = await self._request(
            "POST", f"{self._key_path(license_key)}/time", json_body={"seconds": seconds}
        )
        return self._key_details(data)

    async def delete_key(self, license_key: str) -> None:
        await self._request("DELETE", self._key_path(license_key))

    async def key_logs(self, license_key: str) -> list[KeyLogEntry]:
        data = await self._request("GET", f"{self._key_path(license_key)}/logs")
        return [
            KeyLogEntry(
                identity=item.get("identity"),
                hwid=item.get("hwid"),
                software_version=item.get("software_version"),
                successful=bool(item.get("successful")),
                failure_reason=item.get("failure_reason"),
                ip=item.get("ip"),
                timestamp=parse_timestamp(item.get("timestamp")),
            )
            for item in _as_list(data)
        ]

    # ---------------------------------------------------------------- variables

    async def get_variable(self, name: str) -> Variable:
        return self._variable(await self._request("GET", self._variable_path(name)))

    async def create_variable(self, name: str, value: str, protected: bool = True) -> Variable:
        body = {"name": name, "value": value, "protected": protected}
        return self._variable(
            await self._request("POST", f"{self._system_path()}/variables", json_body=body)
        )

    async def update_variable(
        self, name: str, value: str, *, protected: bool | None = None
    ) -> Variable:
        body: dict[str, Any] = {"value": value}
        if protected is not None:
            body["protected"] = protected
        return self._variable(
            await self._request("PATCH", self._variable_path(name), json_body=body)
        )

    async def delete_variable(self, name: str) -> None:
        await self._request("DELETE", self._variable_path(name))

    # ---------------------------------------------------------------- resellers

    async def list_resellers(self) -> list[ResellerSummary]:
        data = await self._request("GET", f"{self._system_path()}/resellers")
        return [
            ResellerSummary(token=str(item.get("token") or ""), name=str(item.get("name") or ""))
            for item in _as_list(data)
        ]

    async def get_reseller(self, token: str) -> Reseller:
        return self._reseller(await self._request("GET", self._reseller_path(token)))

    async def create_reseller(
        self,
        name: str,
        *,
        permissions: ResellerPermissions,
        allowance: Allowance | None = None,
    ) -> Reseller:
        cleaned = name.strip()
        if not cleaned or len(cleaned) > RESELLER_NAME_MAX:
            raise ValueError(
                f"the reseller name must be 1-{RESELLER_NAME_MAX} characters after trimming."
            )
        body: dict[str, Any] = {"name": cleaned, "permissions": permissions.to_body()}
        body.update((allowance or Allowance(enabled=False)).to_body())
        return self._reseller(
            await self._request("POST", f"{self._system_path()}/resellers", json_body=body)
        )

    async def get_reseller_permissions(self, token: str) -> ResellerPermissions:
        return self._permissions(await self._request("GET", f"{self._reseller_path(token)}/permissions"))

    async def set_reseller_permissions(
        self, token: str, permissions: ResellerPermissions
    ) -> ResellerPermissions:
        data = await self._request(
            "PATCH",
            f"{self._reseller_path(token)}/permissions",
            json_body={"permissions": permissions.to_body()},
        )
        return self._permissions(data)

    async def get_reseller_allowance(self, token: str) -> Allowance | None:
        return self._allowance(await self._request("GET", f"{self._reseller_path(token)}/allowance"))

    async def set_reseller_allowance(self, token: str, allowance: Allowance) -> Allowance | None:
        data = await self._request(
            "PUT", f"{self._reseller_path(token)}/allowance", json_body=allowance.to_body()
        )
        return self._allowance(data)

    async def remove_reseller_allowance(self, token: str) -> None:
        await self._request("DELETE", f"{self._reseller_path(token)}/allowance")

    async def reset_reseller_password(self, token: str) -> str:
        data = await self._request("POST", f"{self._reseller_path(token)}/password-reset")
        if isinstance(data, Mapping):
            return str(data.get("password") or "")
        return str(data or "")

    async def delete_reseller(self, token: str) -> None:
        await self._request("DELETE", self._reseller_path(token))

    # ----------------------------------------------------------------- security

    async def ip_lookup(self, ip: str) -> IpLookup:
        data = await self._request("GET", f"{self._system_path()}/security/ip-lookup", params={"ip": ip})
        return IpLookup(
            ip=str(data.get("ip") or ip),
            asn=data.get("asn"),
            as_name=data.get("as_name"),
            country=data.get("country"),
            location=data.get("location"),
            possible_vpn=data.get("possible_vpn"),
            provider_type=data.get("provider_type"),
        )

    # ----------------------------------------------------------------- internals

    def _system_path(self) -> str:
        return f"/systems/{quote(self._system_id, safe='')}"

    def _key_path(self, license_key: str) -> str:
        return f"{self._system_path()}/keys/{quote(license_key.strip(), safe='')}"

    def _variable_path(self, name: str) -> str:
        return f"{self._system_path()}/variables/{quote(name.strip(), safe='')}"

    def _reseller_path(self, token: str) -> str:
        return f"{self._system_path()}/resellers/{quote(token.strip(), safe='')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        response = await self._attempt(method, url, params=params, json_body=json_body)
        if response.status == 429:  # one retry honouring Retry-After
            delay = _retry_after_seconds(response.headers)
            await asyncio.sleep(delay)
            response = await self._attempt(method, url, params=params, json_body=json_body)

        body: Any = {}
        malformed = False
        if response.text.strip():
            try:
                body = json.loads(response.text)
            except json.JSONDecodeError:
                malformed = True

        if not 200 <= response.status < 300:
            raise _api_error(response.status, None if malformed else body)
        if malformed:
            raise ApiTransportError("The API returned a non-JSON response body.")
        return body.get("data", body) if isinstance(body, dict) else body

    async def _attempt(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None,
        json_body: Any | None,
    ) -> TransportResponse:
        await self._limiter.acquire()
        return await self._transport.request(
            method, url, headers=self._headers, params=params, json_body=json_body
        )

    def _system_details(self, data: Mapping[str, Any]) -> SystemDetails:
        return SystemDetails(
            id=str(data.get("id") or self._system_id),
            name=str(data.get("name") or ""),
            version=data.get("version"),
            program_hash=data.get("program_hash"),
            paused=bool(data.get("paused")),
            paused_at=parse_timestamp(data.get("paused_at")),
        )

    def _pause_result(self, data: Mapping[str, Any]) -> PauseResult:
        return PauseResult(
            system_id=str(data.get("system_id") or self._system_id),
            paused=bool(data.get("paused")),
            paused_at=parse_timestamp(data.get("paused_at")),
            deleted_sessions=int(data.get("deleted_sessions") or 0),
            compensated_keys=int(data.get("compensated_keys") or 0),
            compensated_seconds=int(data.get("compensated_seconds") or 0),
        )

    def _key_details(self, data: Mapping[str, Any]) -> KeyDetails:
        return KeyDetails(
            license_key=str(data.get("license_key") or ""),
            claim_type=data.get("claim_type"),
            username=data.get("username"),
            hwid_is_set=bool(data.get("hwid_is_set")),
            frozen=bool(data.get("frozen")),
            free_trial=bool(data.get("free_trial")),
            notes=data.get("notes"),
            expires_at=parse_timestamp(data.get("expires_at")),
            created_at=parse_timestamp(data.get("created_at")),
            redeemed_at=parse_timestamp(data.get("redeemed_at")),
        )

    def _variable(self, data: Mapping[str, Any]) -> Variable:
        return Variable(
            name=str(data.get("name") or ""),
            value=str(data.get("value") or ""),
            protected=bool(data.get("protected")),
        )

    def _reseller(self, data: Mapping[str, Any]) -> Reseller:
        return Reseller(
            token=str(data.get("token") or ""),
            name=str(data.get("name") or ""),
            permissions=self._permissions(data),
            allowance=self._allowance(data.get("allowances")),
            password=data.get("password"),
        )

    @staticmethod
    def _permissions(data: Any) -> ResellerPermissions:
        # The permissions endpoint returns the bare object; a full reseller
        # response nests it under "permissions".
        if isinstance(data, Mapping) and isinstance(data.get("permissions"), Mapping):
            data = data["permissions"]
        return ResellerPermissions.from_body(data if isinstance(data, Mapping) else {})

    @staticmethod
    def _allowance(data: Any) -> Allowance | None:
        if not isinstance(data, Mapping) or not data:
            return None
        return Allowance.from_body(data)


def _api_error(status: int, body: Any) -> ManagementApiError:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return ManagementApiError(
            status, str(error.get("code") or "UNKNOWN"), str(error.get("message") or "")
        )
    return ManagementApiError(status, "UNKNOWN", "The API returned an unexpected error body.")


def _retry_after_seconds(headers: Mapping[str, str]) -> float:
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return min(max(float(value), 1.0), 60.0)
            except ValueError:
                break
    return 5.0


def _as_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
