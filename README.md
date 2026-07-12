# bs-be18000

A Python client and CLI for the ASUS ROG Strix GS-BE18000 router's web API.

## Background

This router has no published public API. Like all AsusWRT-powered routers, it exposes the same
HTTP(S) JSON API that its own web UI uses to talk to it. The login flow and hook query mechanism
below have been confirmed against a real GS-BE18000 (firmware nonce-based login, packet-captured
to verify the exact request/response shapes):

- **Login** is a nonce/cnonce challenge, not plain base64(user:pass): `POST get_Nonce.cgi` with
  `{"id": <random>}` to get a `nonce`, then `POST login_v2.cgi` with
  `login_authorization = sha256("user:nonce:password:cnonce")` plus a handful of other form
  fields. On success the session token comes back as a `Set-Cookie: asus_token=...` header (not
  a JSON body) — `httpx`'s cookie jar picks this up automatically.
- **Reading state** is `GET appGet.cgi?hook=<fn1>(<args1>);<fn2>(<args2>);...` — e.g.
  `nvram_get(productid);nvram_get(firmver);get_clientlist();`. Confirmed working: `nvram_get`
  for NVRAM values and `get_clientlist` for connected devices. Note `nvram_get` only ever takes
  one variable per call — fetching several means chaining several `nvram_get(...)` calls in one
  request, not comma-joining variable names into a single call.
- **Settings/actions** go through `POST applyapp.cgi` with `rc_service=<name>` — this part is
  still based on general AsusWRT convention rather than a packet capture (we haven't triggered a
  real settings change to confirm it), so treat `run_service`/`reboot`/`restart_wireless` as
  less-verified than the read path above.

The handful of high-level convenience methods (`get_device_info`, `get_wan_status`,
`get_clients`) use NVRAM keys that are either confirmed above or have been stable across AsusWRT
firmware for years, and have been verified end-to-end against a real GS-BE18000. Note that
`WanStatus.state` is the raw `wan0_state_t` NVRAM code (e.g. `"2"`), not decoded into a label —
cross-reference it against the WAN status shown in the router's own web UI if you need to know
what a given code means, since guessing at that mapping risked getting it wrong. If a value comes
back empty on your unit, open the router's web UI, watch the Network tab while it loads the
relevant page, and adjust the key/hook name accordingly — or just
call `query_hooks`/`get_nvram` directly with the right name.

## Install

From PyPI, as a standalone CLI (installs to `~/.local/bin` via `uv tool`, isolated from any
other project's environment):

```
uv tool install bs-be18000
```

Or with `pip`:

```
pip install bs-be18000
```

Either way, both the `bs-be18000` command and the `bs_be18000` library are available.

### From source (development)

Installs into the project's own `.venv`:

```
uv sync
```

To use the `bs-be18000` CLI as a standalone command from anywhere while tracking local source
changes (installs to `~/.local/bin` via `uv tool`, in editable mode):

```
make install     # or: uv tool install --editable .
```

## Library usage

```python
from bs_be18000 import RouterClient

with RouterClient("192.168.1.1", "admin", "hunter2") as router:
    print(router.get_device_info())
    print(router.get_wan_status())
    for client in router.get_clients():
        print(client)
```

Escape hatches for anything not wrapped above:

```python
router.get_nvram("wl0_ssid", "wl1_ssid")
router.query_hooks([("nvram_get", "productid"), ("get_clientlist", "")])
router.run_service("restart_qos")
```

## CLI usage

Credentials resolve from flags, then environment variables, then an interactive password
prompt — nothing is ever written to disk. Set all three env vars once per shell session and
every command below just works, with no re-entering the password each time:

```
export BS_BE18000_HOST=192.168.1.1
export BS_BE18000_USERNAME=admin
export BS_BE18000_PASSWORD=hunter2   # leading space keeps it out of shell history
                                     # (bash/zsh with HISTCONTROL=ignorespace or
                                     # HIST_IGNORE_SPACE set)

bs-be18000 device info
bs-be18000 wan status
bs-be18000 clients list
bs-be18000 nvram get productid firmver
bs-be18000 system reboot
bs-be18000 --json device info   # machine-readable output
```

Run `bs-be18000 --help` or `bs-be18000 <command> --help` for the full command tree.

## Development

```
uv run pytest       # unit tests, router HTTP calls mocked with respx
uv run ruff check .
uv run mypy src tests
```
