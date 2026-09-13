# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for spreading a poll's entity writes across event-loop ticks.

A large cluster flushes ~150+ entity states per poll; writing them all in one
tick briefly stalls the loop. The coordinator batches them in chunks with a
yield between, so no single tick does the whole burst. These tests pin that
behaviour (and that every listener still gets called).
"""

from collections.abc import Callable

from homeassistant.core import HomeAssistant

from custom_components.aruba_instant_ap.sensor import (
    _LISTENER_FLUSH_CHUNK,
    ArubaAPCoordinator,
)


def _coordinator(hass: HomeAssistant) -> ArubaAPCoordinator:
    return ArubaAPCoordinator(hass, "host", "public", 161, "2c", 30)


def _appender(calls: list[int], i: int) -> Callable[[], None]:
    """A typed listener callback that records that it fired."""

    def _cb() -> None:
        calls.append(i)

    return _cb


def _noop() -> None:
    return None


async def test_small_update_calls_all_in_one_tick(hass: HomeAssistant) -> None:
    """At or below one chunk, listeners fire synchronously — no batching task."""
    coord = _coordinator(hass)
    calls: list[int] = []
    for i in range(_LISTENER_FLUSH_CHUNK):
        coord.async_add_listener(_appender(calls, i))

    coord.async_update_listeners()

    assert len(calls) == _LISTENER_FLUSH_CHUNK  # all done immediately
    assert coord._flush_task is None  # no background flush was needed
    await coord.async_shutdown()


async def test_large_update_is_spread_but_calls_every_listener(
    hass: HomeAssistant,
) -> None:
    """Above one chunk the writes spread across ticks, yet all still fire."""
    coord = _coordinator(hass)
    n = _LISTENER_FLUSH_CHUNK * 3 + 1  # forces several chunks
    calls: list[int] = []
    for i in range(n):
        coord.async_add_listener(_appender(calls, i))

    coord.async_update_listeners()

    # Not the whole burst in this tick — that's the point of the spreading.
    assert len(calls) < n
    assert coord._flush_task is not None

    await hass.async_block_till_done()
    assert len(calls) == n  # every listener written by the time the flush drains
    await coord.async_shutdown()


async def test_new_poll_supersedes_inflight_flush(hass: HomeAssistant) -> None:
    """A newer poll cancels the previous batch instead of double-writing."""
    coord = _coordinator(hass)
    for _ in range(_LISTENER_FLUSH_CHUNK * 3):
        coord.async_add_listener(_noop)

    coord.async_update_listeners()
    first = coord._flush_task
    assert first is not None and not first.done()

    coord.async_update_listeners()  # supersede
    second = coord._flush_task
    assert second is not first  # a fresh batch replaced the old one

    await hass.async_block_till_done()
    assert first.done()  # old batch no longer pending (cancelled/finished)
    await coord.async_shutdown()


async def test_listener_removed_midflush_is_skipped(hass: HomeAssistant) -> None:
    """A listener that unsubscribes mid-flush is skipped, not called after removal.

    An entity removed mid-poll would raise if its write were invoked; that must
    not abort the rest of the poll's writes.
    """
    coord = _coordinator(hass)
    calls: list[int] = []
    unsubs: dict[int, Callable[[], None]] = {}
    n = _LISTENER_FLUSH_CHUNK * 3
    victim = _LISTENER_FLUSH_CHUNK * 2 + 1  # lands in a later chunk

    def _make(i: int) -> Callable[[], None]:
        def _cb() -> None:
            if i == victim:
                raise RuntimeError("write on a removed entity")
            calls.append(i)
            if i == 0:  # first chunk: drop a listener scheduled for a later chunk
                unsubs[victim]()

        return _cb

    for i in range(n):
        unsubs[i] = coord.async_add_listener(_make(i))

    coord.async_update_listeners()
    await hass.async_block_till_done()

    assert victim not in calls  # skipped once it unsubscribed
    assert len(calls) == n - 1  # every other listener still flushed
    await coord.async_shutdown()


async def test_shutdown_cancels_inflight_flush(hass: HomeAssistant) -> None:
    """async_shutdown (invoked on unload) cancels a pending flush batch."""
    coord = _coordinator(hass)
    for _ in range(_LISTENER_FLUSH_CHUNK * 3):
        coord.async_add_listener(_noop)

    coord.async_update_listeners()
    task = coord._flush_task
    assert task is not None and not task.done()

    await coord.async_shutdown()
    await hass.async_block_till_done()
    assert task.cancelled()  # the in-flight batch was cancelled
