"""Command-line interface for the router API client, built on click."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import click

from bs_be18000.client import RouterClient
from bs_be18000.exceptions import AsusRouterError


@dataclass
class Connection:
    """Everything needed to open a `RouterClient`, resolved once at CLI startup.

    `host`/`username`/`password` are left unvalidated here (and password unprompted) so that
    `--help` works anywhere in the command tree without demanding credentials first. They're
    only required once a command actually needs to talk to the router — see `_router` below.
    """

    host: str | None
    username: str | None
    password: str | None
    use_ssl: bool
    verify_ssl: bool
    as_json: bool


@click.group()
@click.option("-H", "--host", envvar="BS_BE18000_HOST", help="Router hostname or IP.")
@click.option("-u", "--username", envvar="BS_BE18000_USERNAME", help="Router admin username.")
@click.option(
    "-p",
    "--password",
    envvar="BS_BE18000_PASSWORD",
    help="Router admin password. Prompted for if not set via flag or $BS_BE18000_PASSWORD.",
)
@click.option("--use-ssl/--no-use-ssl", default=True, help="Connect over HTTPS.")
@click.option(
    "--verify-ssl/--no-verify-ssl",
    default=False,
    help="Verify the router's TLS certificate (routers ship self-signed certs by default).",
)
@click.option(
    "--json", "as_json", is_flag=True, help="Print raw JSON instead of formatted output."
)
@click.pass_context
def cli(
    ctx: click.Context,
    host: str | None,
    username: str | None,
    password: str | None,
    use_ssl: bool,
    verify_ssl: bool,
    as_json: bool,
) -> None:
    """Query and control an ASUS ROG Strix GS-BE18000 router."""
    ctx.obj = Connection(host, username, password, use_ssl, verify_ssl, as_json)


def _require(value: str | None, message: str) -> str:
    if not value:
        raise click.ClickException(message)
    return value


@contextmanager
def _router(ctx: click.Context) -> Iterator[RouterClient]:
    """Open a logged-in `RouterClient`, translating API errors into CLI errors."""
    connection: Connection = ctx.obj
    host = _require(connection.host, "Missing router host: pass --host or set BS_BE18000_HOST.")
    username = _require(
        connection.username,
        "Missing router username: pass --username or set BS_BE18000_USERNAME.",
    )
    password = connection.password or click.prompt("Password", hide_input=True)
    try:
        with RouterClient(
            host, username, password, use_ssl=connection.use_ssl, verify_ssl=connection.verify_ssl
        ) as router:
            yield router
    except AsusRouterError as exc:
        raise click.ClickException(str(exc)) from exc


def _print_fields(obj: Any) -> None:
    for field in dataclasses.fields(obj):
        click.echo(f"{field.name}: {getattr(obj, field.name)}")


def _print_json(data: Any) -> None:
    click.echo(json.dumps(_to_jsonable(data), indent=2))


def _to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


def _print_table(rows: list[dict[str, str]]) -> None:
    if not rows:
        click.echo("(none)")
        return
    columns = list(rows[0].keys())
    widths = {column: max(len(column), *(len(row[column]) for row in rows)) for column in columns}
    click.echo("  ".join(column.ljust(widths[column]) for column in columns))
    click.echo("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        click.echo("  ".join(row[column].ljust(widths[column]) for column in columns))


# -- device --------------------------------------------------------------------


@cli.group()
def device() -> None:
    """Device identity."""


@device.command("info")
@click.pass_context
def device_info(ctx: click.Context) -> None:
    """Show product ID and firmware version."""
    with _router(ctx) as router:
        info = router.get_device_info()
    _print_json(info) if ctx.obj.as_json else _print_fields(info)


# -- wan -------------------------------------------------------------------------


@cli.group()
def wan() -> None:
    """WAN (internet) connection."""


@wan.command("status")
@click.pass_context
def wan_status(ctx: click.Context) -> None:
    """Show WAN connection state, IP, gateway, and DNS."""
    with _router(ctx) as router:
        status = router.get_wan_status()
    _print_json(status) if ctx.obj.as_json else _print_fields(status)


# -- clients -----------------------------------------------------------------------


@cli.group()
def clients() -> None:
    """Devices connected to the router."""


@clients.command("list")
@click.pass_context
def clients_list(ctx: click.Context) -> None:
    """List devices currently connected to the router."""
    with _router(ctx) as router:
        devices = router.get_clients()
    if ctx.obj.as_json:
        _print_json(devices)
        return
    _print_table(
        [
            {
                "mac_address": device.mac_address,
                "name": device.name,
                "ip_address": device.ip_address,
                "online": "yes" if device.is_online else "no",
            }
            for device in devices
        ]
    )


# -- nvram -------------------------------------------------------------------------


@cli.group()
def nvram() -> None:
    """Raw NVRAM access."""


@nvram.command("get")
@click.argument("keys", nargs=-1, required=True)
@click.pass_context
def nvram_get(ctx: click.Context, keys: tuple[str, ...]) -> None:
    """Fetch one or more raw NVRAM values by name."""
    with _router(ctx) as router:
        values = router.get_nvram(*keys)
    if ctx.obj.as_json:
        _print_json(values)
        return
    for key, value in values.items():
        click.echo(f"{key}: {value}")


# -- hook (escape hatch) ------------------------------------------------------------


@cli.group()
def hook() -> None:
    """Raw hook queries — an escape hatch for anything not wrapped above."""


@hook.command("run")
@click.argument("calls", nargs=-1, required=True)
@click.pass_context
def hook_run(ctx: click.Context, calls: tuple[str, ...]) -> None:
    """Run one or more raw hook calls, e.g. 'nvram_get=productid' 'nvram_get=firmver'."""
    hooks = [_parse_hook_call(call) for call in calls]
    with _router(ctx) as router:
        result = router.query_hooks(hooks)
    _print_json(result)


def _parse_hook_call(call: str) -> tuple[str, str]:
    name, _, args = call.partition("=")
    return name, args


# -- service (escape hatch) ---------------------------------------------------------


@cli.group()
def service() -> None:
    """Raw rc_service actions — an escape hatch for anything not wrapped above."""


@service.command("run")
@click.argument("name")
@click.option(
    "--set",
    "extra_pairs",
    multiple=True,
    metavar="KEY=VALUE",
    help="Extra form fields to send alongside the service call.",
)
@click.pass_context
def service_run(ctx: click.Context, name: str, extra_pairs: tuple[str, ...]) -> None:
    """Trigger an rc_service action by name, e.g. 'restart_qos'."""
    extra = dict(pair.split("=", 1) for pair in extra_pairs)
    with _router(ctx) as router:
        result = router.run_service(name, **extra)
    _print_json(result)


# -- system ------------------------------------------------------------------------


@cli.group()
def system() -> None:
    """Whole-device actions."""


@system.command("reboot")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def system_reboot(ctx: click.Context, yes: bool) -> None:
    """Reboot the router."""
    if not yes:
        click.confirm("Reboot the router now?", abort=True)
    with _router(ctx) as router:
        router.reboot()
    click.echo("Reboot triggered.")


@system.command("restart-wireless")
@click.pass_context
def system_restart_wireless(ctx: click.Context) -> None:
    """Restart the wireless radios."""
    with _router(ctx) as router:
        router.restart_wireless()
    click.echo("Wireless restart triggered.")
