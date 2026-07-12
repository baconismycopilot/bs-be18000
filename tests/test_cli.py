"""Tests for the CLI, with the router mocked via respx (same approach as test_client.py)."""

from __future__ import annotations

import json

import httpx
import respx
from click.testing import CliRunner
from conftest import BASE_URL, HOST

from bs_be18000.cli import cli

BASE_ARGS = ["--host", HOST, "--username", "admin", "--password", "hunter2"]


def _mock_login() -> None:
    respx.post(f"{BASE_URL}/get_Nonce.cgi").mock(
        return_value=httpx.Response(200, json={"nonce": "test-nonce"})
    )
    respx.post(f"{BASE_URL}/login_v2.cgi").mock(
        return_value=httpx.Response(200, headers={"set-cookie": "asus_token=abc123; HttpOnly"})
    )
    respx.post(f"{BASE_URL}/Logout.asp").mock(return_value=httpx.Response(200))


@respx.mock
def test_device_info_prints_formatted_fields() -> None:
    _mock_login()
    respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(
            200, json={"productid": "GS-BE18000", "firmver": "3.0.0.6", "buildno": "102"}
        )
    )

    result = CliRunner().invoke(cli, [*BASE_ARGS, "device", "info"])

    assert result.exit_code == 0, result.output
    assert "product_id: GS-BE18000" in result.output
    assert "firmware_version: 3.0.0.6" in result.output


@respx.mock
def test_device_info_json_flag_prints_json() -> None:
    _mock_login()
    respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(
            200, json={"productid": "GS-BE18000", "firmver": "", "buildno": ""}
        )
    )

    result = CliRunner().invoke(cli, [*BASE_ARGS, "--json", "device", "info"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "product_id": "GS-BE18000",
        "firmware_version": "",
        "build_number": "",
    }


@respx.mock
def test_clients_list_prints_table() -> None:
    _mock_login()
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

    result = CliRunner().invoke(cli, [*BASE_ARGS, "clients", "list"])

    assert result.exit_code == 0, result.output
    assert "Laptop" in result.output
    assert "192.168.1.42" in result.output


@respx.mock
def test_nvram_get_prints_key_value_pairs() -> None:
    _mock_login()
    respx.get(f"{BASE_URL}/appGet.cgi").mock(
        return_value=httpx.Response(200, json={"productid": "GS-BE18000"})
    )

    result = CliRunner().invoke(cli, [*BASE_ARGS, "nvram", "get", "productid"])

    assert result.exit_code == 0, result.output
    assert "productid: GS-BE18000" in result.output


@respx.mock
def test_system_reboot_requires_confirmation() -> None:
    result = CliRunner().invoke(cli, [*BASE_ARGS, "system", "reboot"], input="n\n")

    assert result.exit_code != 0


@respx.mock
def test_system_reboot_with_yes_flag_skips_confirmation() -> None:
    _mock_login()
    route = respx.post(f"{BASE_URL}/applyapp.cgi").mock(
        return_value=httpx.Response(200, json={})
    )

    result = CliRunner().invoke(cli, [*BASE_ARGS, "system", "reboot", "--yes"])

    assert result.exit_code == 0, result.output
    assert route.called
    assert "Reboot triggered." in result.output


@respx.mock
def test_authentication_failure_reports_clean_error() -> None:
    respx.post(f"{BASE_URL}/get_Nonce.cgi").mock(
        return_value=httpx.Response(200, json={"nonce": "test-nonce"})
    )
    respx.post(f"{BASE_URL}/login_v2.cgi").mock(return_value=httpx.Response(200, json={}))

    result = CliRunner().invoke(cli, [*BASE_ARGS, "device", "info"])

    assert result.exit_code != 0
    assert "Login failed" in result.output
