# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for the stable per-AP "Started" timestamp.

Mirror of test_client_start_time.py for the AP boot-time path.  The coordinator
derives each AP's boot time as ``now - uptime``; that raw value jitters a few
seconds every poll (scheduling slack + the Timeticks // 100 truncation), so it
must be held stable within ``_BOOT_TIME_TOLERANCE_S`` and only move on a real
change (reboot / clock correction).

Unlike the client tracking dict, ``_prev_ap_boot`` is intentionally *not*
pruned — the AP set in a cluster is small and stable, so there is no unbounded
growth to guard against (hence no pruning test here).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from custom_components.aruba_instant_ap.const import (
    OID_AP_NAME,
    OID_AP_UPTIME,
)
from custom_components.aruba_instant_ap.sensor import (
    _BOOT_TIME_TOLERANCE_S,
    ArubaAPCoordinator,
)

_AP_MAC = "aa:bb:cc:44:55:66"
# AP table is indexed by the 6-octet MAC suffix (parsed tail=False).
_MAC_SUFFIX = ".".join(str(int(b, 16)) for b in _AP_MAC.split(":"))
_BASE = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)


def _walk(uptime_seconds: int | None):
    """Build a fake _walk that reports one AP with the given uptime.

    uptime_seconds=None drops the AP entirely (absent from the walk).
    """

    async def _fake_walk(oid: str) -> dict[str, str]:
        if uptime_seconds is None:
            return {}
        if oid == OID_AP_NAME:
            return {f"{OID_AP_NAME}.{_MAC_SUFFIX}": "AP-Test"}
        if oid == OID_AP_UPTIME:
            # aiAPUptime is in hundredths of a second.
            return {f"{OID_AP_UPTIME}.{_MAC_SUFFIX}": str(uptime_seconds * 100)}
        return {}

    return _fake_walk


async def _poll(coord, *, at: datetime, uptime_seconds: int | None):
    """Run one coordinator update with a frozen clock and return the AP dataclass."""
    with (
        patch.object(coord, "_walk", _walk(uptime_seconds)),
        patch(
            "custom_components.aruba_instant_ap.sensor.dt_util.utcnow",
            return_value=at,
        ),
    ):
        data = await coord._async_update_data()
    return data.aps.get(_AP_MAC)


def _coordinator(hass) -> ArubaAPCoordinator:
    return ArubaAPCoordinator(hass, "host", "public", 161, "2c", 30)


async def test_boot_time_held_stable_within_tolerance(hass):
    """Poll jitter inside the tolerance must not move the reported boot time."""
    coord = _coordinator(hass)

    # Poll 1: 1 h uptime → boot = base - 3600 s.
    ap1 = await _poll(coord, at=_BASE, uptime_seconds=3600)
    assert ap1.boot_time == _BASE - timedelta(seconds=3600)

    # Poll 2: 30 s later but uptime only advanced 28 s (2 s of jitter, well
    # within tolerance) → boot time held at the poll-1 value.
    assert 2 <= _BOOT_TIME_TOLERANCE_S  # guard: jitter chosen below tolerance
    ap2 = await _poll(coord, at=_BASE + timedelta(seconds=30), uptime_seconds=3628)
    assert ap2.boot_time == ap1.boot_time
    assert coord._prev_ap_boot[_AP_MAC] == ap1.boot_time


async def test_boot_time_moves_on_reboot(hass):
    """A reboot resets uptime; the drift exceeds tolerance so boot time moves."""
    coord = _coordinator(hass)

    ap1 = await _poll(coord, at=_BASE, uptime_seconds=3600)

    # AP rebooted: uptime back to 60 s two minutes later.
    ap2 = await _poll(coord, at=_BASE + timedelta(seconds=120), uptime_seconds=60)
    assert ap2.boot_time != ap1.boot_time
    assert ap2.boot_time == _BASE + timedelta(seconds=120 - 60)
