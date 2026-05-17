# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for decimated emit of throughput, SNR and link speed.

Counters keep being polled every cycle, but these high-rate sensors publish
only every ``record_decimation``-th cycle (phase-staggered per entity).
Throughput's byte reference advances *only* on emit cycles, so the published
rate is the exact average across the whole window — bytes that crossed during a
skipped cycle are still counted. SNR (continuous) publishes the window mean;
TX/RX link speed (discrete MCS) publish the latest sample seen in the window.
Between emits the value is held so the recorder dedupes it. Retry rates are
*not* decimated — they stay standard per-poll.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from custom_components.aruba_instant_ap.const import (
    OID_CLIENT_IP,
    OID_CLIENT_RX_BYTES,
    OID_CLIENT_RX_RATE,
    OID_CLIENT_RX_RETRIES,
    OID_CLIENT_SNR,
    OID_CLIENT_SPEED,
    OID_CLIENT_TX_BYTES,
    OID_CLIENT_TX_RETRIES,
)
from custom_components.aruba_instant_ap.sensor import ArubaAPCoordinator

_CLIENT_MAC = "aa:bb:cc:11:22:33"
# Client table is indexed by the 6-octet MAC suffix (parsed tail=True).
_MAC_SUFFIX = ".".join(str(int(b, 16)) for b in _CLIENT_MAC.split(":"))
_BASE = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)


def _walk(*, tx=None, rx=None, snr=None, speed=None, retries=None, present=True):
    """Fake _walk reporting one client with the given counters/gauges."""

    async def _fake_walk(oid: str) -> dict[str, str]:
        if not present:
            return {}
        if oid == OID_CLIENT_IP:
            return {f"{OID_CLIENT_IP}.{_MAC_SUFFIX}": "192.0.2.10"}
        if oid == OID_CLIENT_TX_BYTES and tx is not None:
            return {f"{OID_CLIENT_TX_BYTES}.{_MAC_SUFFIX}": str(tx)}
        if oid == OID_CLIENT_RX_BYTES and rx is not None:
            return {f"{OID_CLIENT_RX_BYTES}.{_MAC_SUFFIX}": str(rx)}
        if oid == OID_CLIENT_SNR and snr is not None:
            return {f"{OID_CLIENT_SNR}.{_MAC_SUFFIX}": str(snr)}
        # TX and RX link speed share the test's `speed` value.
        if oid in (OID_CLIENT_SPEED, OID_CLIENT_RX_RATE) and speed is not None:
            return {f"{oid}.{_MAC_SUFFIX}": str(speed)}
        if (
            oid in (OID_CLIENT_TX_RETRIES, OID_CLIENT_RX_RETRIES)
            and retries is not None
        ):
            return {f"{oid}.{_MAC_SUFFIX}": str(retries)}
        return {}

    return _fake_walk


async def _poll(coord, *, mono: float, at: datetime, **walk):
    """Run one coordinator update with frozen clocks; return the client dict."""
    with (
        patch.object(coord, "_walk", _walk(**walk)),
        patch(
            "custom_components.aruba_instant_ap.sensor.dt_util.utcnow",
            return_value=at,
        ),
        patch(
            "custom_components.aruba_instant_ap.sensor.time.monotonic",
            return_value=mono,
        ),
    ):
        data = await coord._async_update_data()
    return next((c for c in data.clients if c["mac"] == _CLIENT_MAC), None)


def _coordinator(hass) -> ArubaAPCoordinator:
    coord = ArubaAPCoordinator(hass, "host", "public", 161, "2c", 30)
    # Deterministic phase: emit on odd poll cycles (1, 3, …), bypassing the
    # per-MAC hash so the window math is what's under test.
    coord._emit_now = lambda key: coord._poll_cycle % 2 == 1
    return coord


async def test_rate_window_is_lossless_across_skipped_cycle(hass):
    """The published rate averages the whole window, not just the last cycle."""
    coord = _coordinator(hass)

    # Cycle 0 (poll 1): first sighting → seed the reference, no rate yet.
    c1 = await _poll(coord, mono=1000.0, at=_BASE, tx=0, rx=0)
    assert "tx_rate" not in c1
    assert coord._prev_client_counters[_CLIENT_MAC][2] == 1000.0  # ref ts

    # Cycle 1 (poll 2): emit. 6000 B over 60 s → 100 B/s.
    c2 = await _poll(
        coord, mono=1060.0, at=_BASE + timedelta(seconds=60), tx=6000, rx=6000
    )
    assert c2["tx_rate"] == 100
    assert c2["rx_rate"] == 100
    assert coord._prev_client_counters[_CLIENT_MAC][2] == 1060.0  # ref advanced

    # Cycle 2 (poll 3): no emit. Counter idle this minute; value is held and
    # the reference does NOT advance (so the next window still spans poll 2→4).
    c3 = await _poll(
        coord, mono=1120.0, at=_BASE + timedelta(seconds=120), tx=6000, rx=6000
    )
    assert c3["tx_rate"] == 100  # carried forward (recorder dedupes)
    assert coord._prev_client_counters[_CLIENT_MAC][2] == 1060.0  # ref held

    # Cycle 3 (poll 4): emit. 12000 B since the poll-2 reference over 120 s →
    # 100 B/s. A naive "last cycle only" delta (C3-C2)/60 would be 200 and
    # would have lost the idle minute — asserting 100 proves it's lossless.
    c4 = await _poll(
        coord, mono=1180.0, at=_BASE + timedelta(seconds=180), tx=18000, rx=18000
    )
    assert c4["tx_rate"] == 100
    assert c4["rx_rate"] == 100
    assert coord._prev_client_counters[_CLIENT_MAC][2] == 1180.0


async def test_gauges_show_immediately_then_decimate(hass):
    """SNR publishes the window mean; TX/RX link speed publish the latest.

    Both kinds show their raw value on first sighting and are held between
    emit cycles so the recorder dedupes them.
    """
    coord = _coordinator(hass)

    # Cycle 0: first sighting → raw values shown right away (not blank).
    c1 = await _poll(coord, mono=1000.0, at=_BASE, tx=0, rx=0, snr=30, speed=300)
    assert c1["snr_db"] == 30
    assert c1["speed_mbps"] == 300
    assert c1["rx_speed_mbps"] == 300

    # Cycle 1 (emit): only this cycle's sample is in the window.
    c2 = await _poll(
        coord,
        mono=1060.0,
        at=_BASE + timedelta(seconds=60),
        tx=1,
        rx=1,
        snr=40,
        speed=400,
    )
    assert c2["snr_db"] == 40
    assert c2["speed_mbps"] == 400

    # Cycle 2 (no emit): samples accumulate, displayed values held.
    c3 = await _poll(
        coord,
        mono=1120.0,
        at=_BASE + timedelta(seconds=120),
        tx=2,
        rx=2,
        snr=50,
        speed=500,
    )
    assert c3["snr_db"] == 40
    assert c3["speed_mbps"] == 400

    # Cycle 3 (emit): SNR = mean of the window's samples; link speed = the
    # latest real sample seen in the window (no off-ladder averaging).
    c4 = await _poll(
        coord,
        mono=1180.0,
        at=_BASE + timedelta(seconds=180),
        tx=3,
        rx=3,
        snr=60,
        speed=600,
    )
    assert c4["snr_db"] == 55  # mean(50, 60)
    assert c4["speed_mbps"] == 600  # latest sample (TX link speed)
    assert c4["rx_speed_mbps"] == 600  # latest sample (RX link speed)


async def test_decimation_state_pruned_when_client_disappears(hass):
    """Held values / SNR accumulators must not grow unbounded."""
    coord = _coordinator(hass)

    await _poll(coord, mono=1000.0, at=_BASE, tx=0, rx=0, snr=30)
    await _poll(
        coord, mono=1060.0, at=_BASE + timedelta(seconds=60), tx=6000, rx=6000, snr=40
    )
    assert _CLIENT_MAC in coord._client_out

    gone = await _poll(
        coord, mono=1120.0, at=_BASE + timedelta(seconds=120), present=False
    )
    assert gone is None
    assert coord._client_out == {}
    assert coord._client_avg_acc == {}
    assert coord._prev_client_counters == {}
    assert coord._prev_client_retry == {}


async def test_retry_rates_stay_per_poll_not_decimated(hass):
    """Retry rates publish every poll even on non-emit cycles."""
    coord = _coordinator(hass)
    # Force *no* emit cycles at all — throughput would never publish, but
    # retry rates must still update every poll against the prior poll.
    coord._emit_now = lambda key: False

    c1 = await _poll(coord, mono=1000.0, at=_BASE, tx=0, rx=0, retries=0)
    assert "tx_retry_rate" not in c1  # no prior reference yet
    assert "tx_rate" not in c1  # throughput never emits here

    # 120 retries over the 60 s since the prior poll → 2.0 frames/s.
    c2 = await _poll(
        coord, mono=1060.0, at=_BASE + timedelta(seconds=60), tx=1, rx=1, retries=120
    )
    assert c2["tx_retry_rate"] == 2.0
    assert c2["rx_retry_rate"] == 2.0
    assert "tx_rate" not in c2  # still decimated away

    # Next poll, still no emit: retry rate is recomputed vs the *immediately*
    # prior poll (per-poll reference), not held.
    c3 = await _poll(
        coord, mono=1120.0, at=_BASE + timedelta(seconds=120), tx=2, rx=2, retries=180
    )
    assert c3["tx_retry_rate"] == 1.0  # 60 retries / 60 s


async def test_record_decimation_config_controls_emit_cadence(hass):
    """The per-entry record_decimation value drives _emit_now."""
    every_poll = ArubaAPCoordinator(
        hass, "h", "public", 161, "2c", 30, record_decimation=1
    )
    every_poll._poll_cycle = 7
    assert every_poll._emit_now("any-key") is True  # 1 = never decimate

    decim = ArubaAPCoordinator(hass, "h", "public", 161, "2c", 30, record_decimation=3)
    # A key emits on exactly one residue class mod 3 → once per 3 cycles.
    emits = 0
    for cycle in range(9):
        decim._poll_cycle = cycle
        if decim._emit_now("k"):
            emits += 1
    assert emits == 3  # 9 cycles / N=3 → 3 emits

    # Zero/negative is coerced to 1 (never decimate).
    floored = ArubaAPCoordinator(
        hass, "h", "public", 161, "2c", 30, record_decimation=0
    )
    assert floored._record_decimation == 1
