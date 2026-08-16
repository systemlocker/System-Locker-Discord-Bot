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
