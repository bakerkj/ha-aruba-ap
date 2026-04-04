# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Async SNMP helper for Aruba Instant AP (puresnmp 2.x)."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from puresnmp import Client, V1, V2C
from puresnmp.transport import send_udp
from x690.types import ObjectIdentifier, OctetString

_LOGGER = logging.getLogger(__name__)

_PLUGINS_PREWARMED = False


def _prewarm_plugins() -> None:
    """Pre-discover puresnmp plugins and patch the module-level create functions
    to use cached Loaders.

    puresnmp creates a NEW ``Loader`` on every ``mpm.create()`` /
    ``security.create()`` call and each Loader runs ``pkgutil.iter_modules``
    (which calls ``os.listdir``) during its first ``discover_plugins()`` call.
    Because those functions are called inside ``Client()`` and ultimately inside
    every SNMP walk, the listdir fires on every single ``Client()`` instantiation,
    triggering HA's blocking-call detector.

    This function runs the discovery once in an executor thread, then replaces
    the module-level ``create`` callables with versions that reuse a single
    pre-populated ``Loader`` instance, so no further filesystem I/O occurs.
    """
    from puresnmp.exc import UnknownMessageProcessingModel, UnknownSecurityModel
    from puresnmp.plugins import mpm as _mpm, security as _sec
    from puresnmp.plugins.pluginbase import Loader, discover_plugins

    # ── MPM plugins ──────────────────────────────────────────────────────────
    _mpm_loader = Loader("puresnmp_plugins.mpm", _mpm.is_valid_mpm_plugin)
    _mpm_loader.discovered_plugins = discover_plugins(
        "puresnmp_plugins.mpm", _mpm.is_valid_mpm_plugin
    )

    def _cached_mpm_create(identifier, transport_handler, lcd):
        result = _mpm_loader.create(identifier)
        if result is None:
            raise UnknownMessageProcessingModel(
                "puresnmp_plugins.mpm",
                identifier,
                sorted(_mpm_loader.discovered_plugins.keys()),
            )
        return result.create(transport_handler, lcd)  # type: ignore

    _mpm.create = _cached_mpm_create  # type: ignore[assignment]

    # ── Security plugins ─────────────────────────────────────────────────────
    _sec_loader = Loader("puresnmp_plugins.security", _sec.is_valid_sec_plugin)
    _sec_loader.discovered_plugins = discover_plugins(
        "puresnmp_plugins.security", _sec.is_valid_sec_plugin
    )

    def _cached_sec_create(identifier):
        result = _sec_loader.create(identifier)
        if result is None:
            raise UnknownSecurityModel(
                "puresnmp_plugins.security",
                identifier,
                sorted(_sec_loader.discovered_plugins.keys()),
            )
        return result.create()  # type: ignore

    _sec.create = _cached_sec_create  # type: ignore[assignment]

    # The mpm plugins (v1, v2c, v3) captured ``security.create`` at import time
    # via ``from puresnmp.plugins.security import create as create_sm``.
    # Patching ``_sec.create`` doesn't reach those captured references; patch
    # each mpm plugin module directly.
    import puresnmp_plugins.mpm.v1 as _v1
    import puresnmp_plugins.mpm.v2c as _v2c

    _v1.create_sm = _cached_sec_create  # type: ignore[attr-defined]
    _v2c.create_sm = _cached_sec_create  # type: ignore[attr-defined]


async def async_prewarm_plugins(hass) -> None:
    """Run plugin pre-warm exactly once per process lifetime."""
    global _PLUGINS_PREWARMED
    if _PLUGINS_PREWARMED:
        return
    await hass.async_add_executor_job(_prewarm_plugins)
    _PLUGINS_PREWARMED = True
    _LOGGER.debug("puresnmp plugins pre-loaded")


def _credentials(community: str, snmp_version: str):
    """Return puresnmp credentials object for the given version."""
    return V1(community) if snmp_version == "v1" else V2C(community)


def _make_sender(timeout: int, retries: int):
    """Return a sender with custom timeout and retry settings."""
    return partial(send_udp, timeout=timeout, retries=retries)


def _value_to_str(value) -> str:
    """Convert a puresnmp value to a string.

    Matches the format pysnmp prettyPrint() produced so sensor.py parsers
    (``_parse_hex_mac``, ``_as_int``, etc.) continue to work unchanged:
    - OctetString of printable ASCII  → decoded text (e.g. "AP-Name")
    - OctetString of binary bytes     → "0x<hex>" (e.g. "0x1c28afc34624")
    - IpAddress                       → "192.168.1.1"
    - Integer / Counter / TimeTicks   → plain decimal string
    """
    if isinstance(value, OctetString):
        raw = value.value
        if not raw:
            return ""
        if all(0x20 <= b < 0x7F for b in raw):
            return raw.decode("ascii")
        return "0x" + raw.hex()
    return str(value.value)


async def async_snmp_get(
    host: str,
    community: str,
    snmp_port: int,
    oid: str,
    timeout: int = 10,
    retries: int = 3,
    snmp_version: str = "v2c",
) -> str | None:
    """Async SNMP GET for a single OID. Returns None on any failure."""
    if not oid or not oid.strip():
        return None
    try:
        client = Client(
            host,
            _credentials(community, snmp_version),
            port=snmp_port,
            sender=_make_sender(timeout, retries),
        )
        value = await client.get(ObjectIdentifier(oid))
        return _value_to_str(value)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _LOGGER.debug("SNMP GET failed on %s (oid=%s): %s", host, oid, exc)
        return None


async def async_snmp_walk(
    host: str,
    community: str,
    snmp_port: int,
    base_oid: str,
    timeout: int = 10,
    retries: int = 3,
    snmp_version: str = "v2c",
) -> dict[str, str]:
    """Async SNMP GETBULK walk. Returns {full_oid_str: value_str} for all OIDs under base_oid.

    Falls back to GETNEXT walk for SNMPv1 (which does not support GETBULK).
    """
    if not base_oid or not base_oid.strip():
        return {}

    results: dict[str, str] = {}
    try:
        client = Client(
            host,
            _credentials(community, snmp_version),
            port=snmp_port,
            sender=_make_sender(timeout, retries),
        )
        oid_obj = ObjectIdentifier(base_oid)
        walker = (
            client.walk([oid_obj])
            if snmp_version == "v1"
            else client.bulkwalk([oid_obj], bulk_size=25)
        )
        async for vb in walker:
            oid_str = str(vb.oid)
            if not oid_str.startswith(base_oid):
                break
            results[oid_str] = _value_to_str(vb.value)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _LOGGER.debug("SNMP WALK failed on %s (%s): %s", host, base_oid, exc)
    return results
