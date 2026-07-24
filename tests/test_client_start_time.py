# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for the stable per-client "Started" timestamp.

The coordinator derives each client's start time as ``now - uptime``.  That
raw value jitters a few seconds every poll (scheduling slack + the Timeticks
// 100 truncation), so it must be held stable within ``_BOOT_TIME_TOLERANCE_S``
and only move on a real change (reconnect / clock correction).  Stale clients
must also be pruned from the tracking dict so it can't grow unbounded.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from custom_components.aruba_instant_ap.const import (
    OID_CLIENT_IP,
    OID_CLIENT_UPTIME,
)
from custom_components.aruba_instant_ap.sensor import (
    _BOOT_TIME_TOLERANCE_S,
    ArubaAPCoordinator,
)

_CLIENT_MAC = "aa:bb:cc:11:22:33"
# Client table is indexed by the 6-octet MAC suffix (parsed tail=True).
_MAC_SUFFIX = ".".join(str(int(b, 16)) for b in _CLIENT_MAC.split(":"))
_BASE = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)


def _walk(uptime_seconds: int | None):
    """Build a fake _walk that reports one client with the given uptime.

    uptime_seconds=None drops the client entirely (absent from the walk).
    """

    async def _fake_walk(oid: str) -> dict[str, str]:
        if uptime_seconds is None:
            return {}
        if oid == OID_CLIENT_IP:
            return {f"{OID_CLIENT_IP}.{_MAC_SUFFIX}": "192.0.2.10"}
        if oid == OID_CLIENT_UPTIME:
            # Timeticks are centiseconds.
            return {f"{OID_CLIENT_UPTIME}.{_MAC_SUFFIX}": str(uptime_seconds * 100)}
        return {}

    return _fake_walk


async def _poll(coord, *, at: datetime, uptime_seconds: int | None):
    """Run one coordinator update with a frozen clock and return the client dict."""
    with (
        patch.object(coord, "_walk", _walk(uptime_seconds)),
        patch(
            "custom_components.aruba_instant_ap.sensor.dt_util.utcnow",
            return_value=at,
        ),
    ):
        data = await coord._async_update_data()
    return next((c for c in data.clients if c["mac"] == _CLIENT_MAC), None)


def _coordinator(hass) -> ArubaAPCoordinator:
    return ArubaAPCoordinator(hass, "host", "public", 161, "2c", 30)


async def test_start_time_held_stable_within_tolerance(hass):
    """Poll jitter inside the tolerance must not move the reported start time."""
    coord = _coordinator(hass)

    # Poll 1: 1 h uptime → start = base - 3600 s.
    c1 = await _poll(coord, at=_BASE, uptime_seconds=3600)
    assert c1["start_time"] == _BASE - timedelta(seconds=3600)

    # Poll 2: 30 s later but uptime only advanced 28 s (2 s of jitter, well
    # within tolerance) → start time held at the poll-1 value.
    assert 2 <= _BOOT_TIME_TOLERANCE_S  # guard: jitter chosen below tolerance
    c2 = await _poll(coord, at=_BASE + timedelta(seconds=30), uptime_seconds=3628)
    assert c2["start_time"] == c1["start_time"]
    assert coord._prev_client_start[_CLIENT_MAC] == c1["start_time"]


async def test_start_time_moves_on_reconnect(hass):
    """A reconnect resets uptime; the drift exceeds tolerance so start moves."""
    coord = _coordinator(hass)

    c1 = await _poll(coord, at=_BASE, uptime_seconds=3600)

    # Client reconnected: uptime back to 60 s two minutes later.
    c2 = await _poll(coord, at=_BASE + timedelta(seconds=120), uptime_seconds=60)
    assert c2["start_time"] != c1["start_time"]
    assert c2["start_time"] == _BASE + timedelta(seconds=120 - 60)


async def test_stale_client_pruned_from_tracking(hass):
    """A client that disappears must be dropped from _prev_client_start."""
    coord = _coordinator(hass)

    await _poll(coord, at=_BASE, uptime_seconds=3600)
    assert _CLIENT_MAC in coord._prev_client_start

    # Next poll: client gone → not listed and not retained.
    gone = await _poll(coord, at=_BASE + timedelta(seconds=30), uptime_seconds=None)
    assert gone is None
    assert coord._prev_client_start == {}
