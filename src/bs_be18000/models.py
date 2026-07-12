"""Typed containers for the data returned by :class:`bs_be18000.client.RouterClient`.

Each dataclass owns the parsing logic for the raw hook/NVRAM response it's built from, via a
``from_nvram``/``from_hook`` classmethod, so the "what does this field actually look like on the
wire" knowledge lives next to the type it produces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Basic identity of the router, from well-known NVRAM keys."""

    product_id: str
    firmware_version: str
    build_number: str

    @classmethod
    def from_nvram(cls, nvram: dict[str, str]) -> DeviceInfo:
        return cls(
            product_id=nvram.get("productid", ""),
            firmware_version=nvram.get("firmver", ""),
            build_number=nvram.get("buildno", ""),
        )


@dataclass(frozen=True, slots=True)
class WanStatus:
    """WAN (internet) connection state, from well-known NVRAM keys."""

    state: str
    ip_address: str
    gateway: str
    dns: str

    @classmethod
    def from_nvram(cls, nvram: dict[str, str]) -> WanStatus:
        return cls(
            state=nvram.get("wan0_state_t", ""),
            ip_address=nvram.get("wan0_ipaddr", ""),
            gateway=nvram.get("wan0_gateway", ""),
            dns=nvram.get("wan0_dns", ""),
        )


@dataclass(frozen=True, slots=True)
class Client:
    """A device connected to the router, from the ``get_clientlist`` hook.

    The exact shape of ``get_clientlist``'s response has drifted across AsusWRT firmware
    versions; this parses defensively and leaves fields blank rather than raising when a key
    is missing.
    """

    mac_address: str
    name: str
    ip_address: str
    is_online: bool

    @classmethod
    def from_hook(cls, get_clientlist: dict[str, Any]) -> list[Client]:
        mac_addresses = get_clientlist.get("maclist", [])
        clients = []
        for mac_address in mac_addresses:
            info = get_clientlist.get(mac_address, {})
            clients.append(
                cls(
                    mac_address=mac_address,
                    name=info.get("nickName") or info.get("name") or "",
                    ip_address=info.get("ip", ""),
                    is_online=info.get("isOnline") in ("1", 1, True),
                )
            )
        return clients
