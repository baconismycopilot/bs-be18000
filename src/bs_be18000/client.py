"""Synchronous client for the router's web API.

This is the same HTTP(S) JSON API the router's own web UI talks to (there's no published
public API). The protocol: log in with a nonce/cnonce challenge to get a session token
(delivered as a `Set-Cookie` header, which httpx tracks automatically), then send
`GET appGet.cgi?hook=...` queries to read NVRAM values and other state, and `rc_service`
commands to `applyapp.cgi` to trigger actions like a reboot.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from collections.abc import Sequence
from typing import Any, Self, cast

import httpx

from bs_be18000 import endpoints
from bs_be18000.exceptions import AuthenticationError, RequestError
from bs_be18000.models import Client, DeviceInfo, WanStatus

DEFAULT_TIMEOUT = 10.0

_ALPHANUMERIC = string.ascii_letters + string.digits


def _random_string(length: int) -> str:
    return "".join(secrets.choice(_ALPHANUMERIC) for _ in range(length))


def _parse_json(response: httpx.Response) -> Any:
    """Parse a response body as JSON, raising a RequestError with a body preview on failure.

    The router occasionally answers a request that should return JSON with an HTML page
    instead (e.g. a stale/rejected session), which otherwise surfaces as an opaque
    JSONDecodeError deep inside a command.
    """
    try:
        return response.json()
    except ValueError as exc:
        preview = response.text[:200]
        raise RequestError(f"Expected JSON from {response.request.url}, got: {preview!r}") from exc


class RouterClient:
    """A logged-in session with the router.

    Usage:
        with RouterClient("192.168.1.1", "admin", "hunter2") as router:
            print(router.get_device_info())

    Routers ship a self-signed HTTPS certificate, so `verify_ssl` defaults to False.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        use_ssl: bool = True,
        verify_ssl: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._username = username
        self._password = password
        scheme = "https" if use_ssl else "http"
        base_url = f"{scheme}://{host}"
        self._http = httpx.Client(
            base_url=base_url,
            # The router checks Referer as a lightweight CSRF guard on authenticated
            # endpoints, mirroring what its own web UI sends on every request.
            headers={"Referer": f"{base_url}/"},
            verify=verify_ssl,
            timeout=timeout,
        )

    def __enter__(self) -> Self:
        self.login()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Log out and release the underlying HTTP connection."""
        try:
            self.logout()
        finally:
            self._http.close()

    # -- Authentication ----------------------------------------------------

    def login(self) -> None:
        """Authenticate and store the session token for subsequent requests.

        This firmware uses a nonce/cnonce challenge rather than plain base64(user:pass):
        fetch a one-time nonce from `get_Nonce.cgi`, then submit
        `sha256("user:nonce:password:cnonce")` as `login_authorization` to `login_v2.cgi`,
        mirroring what the router's own login page does (see `Main_Login.asp`'s `login()`).
        On success the token comes back as `Set-Cookie: asus_token=...`, not a JSON body.
        """
        request_id = _random_string(10)
        nonce_response = self._post(endpoints.NONCE, json={"id": request_id})
        nonce = _parse_json(nonce_response).get("nonce")
        if not nonce:
            raise RequestError("Router did not return a login nonce")

        cnonce = _random_string(32)
        digest_input = f"{self._username}:{nonce}:{self._password}:{cnonce}"
        login_authorization = hashlib.sha256(digest_input.encode()).hexdigest()

        payload = {
            "group_id": "",
            "action_mode": "",
            "action_script": "",
            "action_wait": "5",
            "current_page": "Main_Login.asp",
            "next_page": "",
            "login_authorization": login_authorization,
            "id": request_id,
            "cnonce": cnonce,
            "login_captcha": "",
        }
        response = self._post(endpoints.LOGIN, payload)
        if not response.cookies.get("asus_token"):
            raise AuthenticationError(f"Login failed for user {self._username!r}")

    def logout(self) -> None:
        """End the router session. Failures are ignored — this is best-effort cleanup."""
        try:
            self._http.post(endpoints.LOGOUT)
        except httpx.HTTPError:
            pass
        finally:
            self._http.cookies.clear()

    # -- Low-level queries ---------------------------------------------------

    def query_hooks(self, calls: Sequence[tuple[str, str]]) -> dict[str, Any]:
        """Run one or more hook function calls against appGet.cgi.

        `calls` is a sequence of (function_name, argument_string) pairs, e.g.
        `[("nvram_get", "productid"), ("nvram_get", "firmver")]` becomes the query string
        `?hook=nvram_get(productid);nvram_get(firmver);`. Repeating a function name (as
        above) is fine — `nvram_get` in particular only ever takes one variable per call.
        """
        request = "".join(f"{name}({args});" for name, args in calls)
        response = self._get(endpoints.HOOK, {"hook": request})
        return cast(dict[str, Any], _parse_json(response))

    def get_nvram(self, *keys: str) -> dict[str, str]:
        """Fetch one or more NVRAM values by name."""
        result = self.query_hooks([("nvram_get", key) for key in keys])
        return {key: result.get(key, "") for key in keys}

    def run_service(self, service: str, **extra: str) -> dict[str, Any]:
        """Trigger an AsusWRT `rc_service` action, e.g. "reboot" or "restart_wireless"."""
        payload = {"action_mode": "apply", "rc_service": service, **extra}
        response = self._post(endpoints.APPLY, payload)
        return cast(dict[str, Any], _parse_json(response))

    # -- High-level convenience ----------------------------------------------

    def get_device_info(self) -> DeviceInfo:
        return DeviceInfo.from_nvram(self.get_nvram("productid", "firmver", "buildno"))

    def get_wan_status(self) -> WanStatus:
        return WanStatus.from_nvram(
            self.get_nvram("wan0_state_t", "wan0_ipaddr", "wan0_gateway", "wan0_dns")
        )

    def get_clients(self) -> list[Client]:
        result = self.query_hooks([("get_clientlist", "")])
        return Client.from_hook(result.get("get_clientlist", {}))

    def reboot(self) -> None:
        self.run_service("reboot")

    def restart_wireless(self) -> None:
        self.run_service("restart_wireless")

    # -- Internals -------------------------------------------------------------

    def _get(self, path: str, params: dict[str, str]) -> httpx.Response:
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise RequestError(f"Request to {path} failed: {exc}") from exc
        if not response.is_success:
            raise RequestError(f"Request to {path} returned HTTP {response.status_code}")
        return response

    def _post(
        self,
        path: str,
        data: dict[str, str] | None = None,
        *,
        json: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = self._http.post(path, data=data, json=json)
        except httpx.HTTPError as exc:
            raise RequestError(f"Request to {path} failed: {exc}") from exc
        if not response.is_success:
            raise RequestError(f"Request to {path} returned HTTP {response.status_code}")
        return response
