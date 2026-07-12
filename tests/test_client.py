"""Tests for RouterClient's HTTP behavior, with the router mocked via respx."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from conftest import BASE_URL, HOST

from bs_be18000.client import RouterClient
from bs_be18000.exceptions import AuthenticationError, RequestError
from bs_be18000.models import Client

NONCE = "test-nonce"


@pytest.fixture
def client() -> RouterClient:
    return RouterClient(HOST, "admin", "hunter2", verify_ssl=False)


def _mock_nonce(nonce: str = NONCE) -> respx.Route:
    return respx.post(f"{BASE_URL}/get_Nonce.cgi").mock(
        return_value=httpx.Response(200, json={"nonce": nonce})
    )


def _mock_login_success(token: str = "abc123") -> respx.Route:
    # A successful login returns the token as a Set-Cookie header, not a JSON body.
    redirect_html = '<HTML><HEAD><meta http-equiv="refresh" content="0; url=GameDashboard.asp">'
    return respx.post(f"{BASE_URL}/login_v2.cgi").mock(
        return_value=httpx.Response(
            200,
            headers={"set-cookie": f"asus_token={token}; HttpOnly"},
            html=redirect_html,
        )
    )


def _mock_login_failure() -> respx.Route:
    # A failed login returns 200 with an HTML redirect back to the login page, no cookie.
    return respx.post(f"{BASE_URL}/login_v2.cgi").mock(
        return_value=httpx.Response(
            200,
            html="<HTML><HEAD><script>window.top.location.href='/Main_Login.asp';</script></HEAD></HTML>",
        )
    )


@respx.mock
def test_login_succeeds_with_valid_token(client: RouterClient) -> None:
    _mock_nonce()
    _mock_login_success()

    client.login()  # must not raise


@respx.mock
def test_requests_send_referer_header(client: RouterClient) -> None:
    # The router treats a missing Referer as unauthenticated on some endpoints.
    nonce_route = _mock_nonce()
    _mock_login_success()

    client.login()

    assert nonce_route.calls.last.request.headers["referer"] == f"{BASE_URL}/"


@respx.mock
def test_login_sends_nonce_challenge_hash(client: RouterClient) -> None:
    _mock_nonce()
    route = _mock_login_success()

    client.login()

    sent = parse_qs(route.calls.last.request.content.decode())
    cnonce = sent["cnonce"][0]
    expected = hashlib.sha256(f"admin:{NONCE}:hunter2:{cnonce}".encode()).hexdigest()
    assert sent["login_authorization"] == [expected]


@respx.mock
def test_login_forwards_token_as_cookie_on_subsequent_requests(client: RouterClient) -> None:
    _mock_nonce()
    _mock_login_success()
    hook_route = respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(200, json={})
    )

    client.login()
    client.query_hooks([("nvram_get", "productid")])

    assert hook_route.calls.last.request.headers["cookie"] == "asus_token=abc123"


@respx.mock
def test_login_without_token_raises_authentication_error(client: RouterClient) -> None:
    _mock_nonce()
    _mock_login_failure()

    with pytest.raises(AuthenticationError):
        client.login()


@respx.mock
def test_login_http_failure_raises_request_error(client: RouterClient) -> None:
    _mock_nonce()
    respx.post(f"{BASE_URL}/login_v2.cgi").mock(return_value=httpx.Response(500))

    with pytest.raises(RequestError):
        client.login()


@respx.mock
def test_login_missing_nonce_raises_request_error(client: RouterClient) -> None:
    respx.post(f"{BASE_URL}/get_Nonce.cgi").mock(return_value=httpx.Response(200, json={}))

    with pytest.raises(RequestError):
        client.login()


@respx.mock
def test_context_manager_logs_in_and_out(client: RouterClient) -> None:
    _mock_nonce()
    login_route = _mock_login_success()
    logout_route = respx.post(f"{BASE_URL}/Logout.asp").mock(return_value=httpx.Response(200))

    with client:
        assert login_route.called

    assert logout_route.called


@respx.mock
def test_query_hooks_builds_semicolon_separated_request(client: RouterClient) -> None:
    # nvram_get only ever takes one variable per call; multiple values need one call each,
    # chained with semicolons in a single request (not a single comma-joined call).
    route = respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(200, json={"productid": "GS-BE18000", "firmver": "3.0.0.6"})
    )

    result = client.query_hooks([("nvram_get", "productid"), ("nvram_get", "firmver")])

    assert (
        route.calls.last.request.url.params["hook"]
        == "nvram_get(productid);nvram_get(firmver);"
    )
    assert result == {"productid": "GS-BE18000", "firmver": "3.0.0.6"}


@respx.mock
def test_get_nvram_returns_requested_keys(client: RouterClient) -> None:
    respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(200, json={"productid": "GS-BE18000", "firmver": "3.0.0.6"})
    )

    values = client.get_nvram("productid", "firmver")

    assert values == {"productid": "GS-BE18000", "firmver": "3.0.0.6"}


@respx.mock
def test_get_nvram_defaults_missing_keys_to_empty_string(client: RouterClient) -> None:
    respx.get(f"{BASE_URL}/appGet.cgi").mock(return_value=httpx.Response(200, json={}))

    values = client.get_nvram("productid")

    assert values == {"productid": ""}


@respx.mock
def test_get_device_info(client: RouterClient) -> None:
    respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(
            200, json={"productid": "GS-BE18000", "firmver": "3.0.0.6", "buildno": "102"}
        )
    )

    info = client.get_device_info()

    assert info.product_id == "GS-BE18000"
    assert info.firmware_version == "3.0.0.6"
    assert info.build_number == "102"


@respx.mock
def test_get_wan_status(client: RouterClient) -> None:
    respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(
            200,
            json={
                "wan0_state_t": "Connected",
                "wan0_ipaddr": "203.0.113.5",
                "wan0_gateway": "203.0.113.1",
                "wan0_dns": "8.8.8.8",
            },
        )
    )

    status = client.get_wan_status()

    assert status.state == "Connected"
    assert status.ip_address == "203.0.113.5"
    assert status.gateway == "203.0.113.1"
    assert status.dns == "8.8.8.8"


@respx.mock
def test_get_clients_parses_maclist(client: RouterClient) -> None:
    respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(
            200,
            json={
                "get_clientlist": {
                    "maclist": ["AA:BB:CC:DD:EE:FF"],
                    "AA:BB:CC:DD:EE:FF": {
                        "nickName": "Laptop",
                        "ip": "192.168.1.42",
                        "isOnline": "1",
                    },
                }
            },
        )
    )

    devices = client.get_clients()

    assert devices == [
        Client(
            mac_address="AA:BB:CC:DD:EE:FF",
            name="Laptop",
            ip_address="192.168.1.42",
            is_online=True,
        )
    ]


@respx.mock
def test_run_service_sends_action_mode_and_service_name(client: RouterClient) -> None:
    route = respx.post(f"{BASE_URL}/applyapp.cgi").mock(
        return_value=httpx.Response(200, json={})
    )

    client.run_service("reboot")

    sent = parse_qs(route.calls.last.request.content.decode())
    assert sent["action_mode"] == ["apply"]
    assert sent["rc_service"] == ["reboot"]


@respx.mock
def test_failed_request_raises_request_error(client: RouterClient) -> None:
    respx.get(f"{BASE_URL}/appGet.cgi").mock(return_value=httpx.Response(503))

    with pytest.raises(RequestError):
        client.query_hooks([("nvram_get", "productid")])


@respx.mock
def test_non_json_response_raises_request_error_with_body_preview(client: RouterClient) -> None:
    # A stale/rejected session can return an HTML page with a 200 status instead of JSON.
    respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(200, html="<HTML><BODY>Session expired</BODY></HTML>")
    )

    with pytest.raises(RequestError, match="Session expired"):
        client.query_hooks([("nvram_get", "productid")])
