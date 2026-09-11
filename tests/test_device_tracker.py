# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for the opt-in presence device_tracker.

A lightweight coordinator polls only the associated-client set, and each
associated MAC becomes a router ScannerEntity — home while the cluster reports
it, not_home once it leaves, unavailable when the poll fails.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.device_tracker import SourceType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aruba_instant_ap.const import (
    CONF_ENABLE_DEVICE_TRACKER,
    CONF_PRESENCE_INTERVAL,
    CONF_TRACKED_CLIENTS,
    DOMAIN,
)
from custom_components.aruba_instant_ap.device_tracker import (
    ArubaClientTracker,
    async_setup_entry,
)

_MAC = "40:2f:86:40:5e:86"
_OTHER_MAC = "24:e8:53:6c:8c:90"


def _make_main(present, clients=None) -> MagicMock:
    """Stand-in for the full telemetry coordinator: the tracker reads client
    names/ips from it, and its lightweight walk drives presence."""
    main = MagicMock()
    main.name = "aruba"
    main.clients_mapped_only = False
    main._mac_hostname_map = {}
    main.last_update_success = True
    main.data.clients = (
        [{"mac": _MAC, "name": "lg-washer", "ip": "192.168.1.5"}]
        if clients is None
        else clients
    )
    main.async_present_client_macs = AsyncMock(return_value=set(present))
    return main


@pytest.fixture
async def setup(hass):
    """Run the platform and tear down the (real) presence coordinator's timer."""
    coordinators: list = []

    async def _do(main, tracked=(_MAC, _OTHER_MAC)) -> list[ArubaClientTracker]:
        entry = MockConfigEntry(
            domain=DOMAIN,
            entry_id="test_entry",
            options={
                CONF_ENABLE_DEVICE_TRACKER: True,
                CONF_PRESENCE_INTERVAL: 15,
                CONF_TRACKED_CLIENTS: list(tracked),
            },
        )
        entry.add_to_hass(hass)
        hass.data.setdefault(DOMAIN, {})["test_entry"] = main
        added: list = []
        await async_setup_entry(hass, entry, lambda es, *a, **k: added.extend(es))
        if added:
            coordinators.append(added[0].coordinator)
        return added

    yield _do

    for coordinator in coordinators:
        await coordinator.async_shutdown()


async def test_one_tracker_per_associated_client(setup):
    added = await setup(_make_main([_MAC, _OTHER_MAC]))
    assert {e._mac for e in added} == {_MAC, _OTHER_MAC}
    assert all(e.source_type is SourceType.ROUTER for e in added)
    assert all(e.mac_address == e._mac for e in added)
    # ScannerEntity keys itself by MAC
    assert {e.unique_id for e in added} == {_MAC, _OTHER_MAC}


async def test_home_while_associated(setup):
    tracker = (await setup(_make_main([_MAC])))[0]
    assert tracker.is_connected is True
    assert tracker.available is True


async def test_not_home_once_it_leaves(setup):
    """A client no longer in the associated set reads not-connected (its poll
    still succeeded), never unavailable — that distinction is the signal."""
    tracker = (await setup(_make_main([_MAC])))[0]
    tracker.coordinator.data.discard(_MAC)
    assert tracker.is_connected is False
    assert tracker.available is True


async def test_unavailable_when_presence_poll_fails(setup):
    tracker = (await setup(_make_main([_MAC])))[0]
    tracker.coordinator.last_update_success = False
    assert tracker.available is False


async def test_name_and_ip_follow_the_client(setup):
    tracker = (await setup(_make_main([_MAC])))[0]
    assert tracker.name == "lg-washer"
    assert tracker.hostname == "lg-washer"
    assert tracker.ip_address == "192.168.1.5"


async def test_name_falls_back_to_mac(setup):
    tracker = (await setup(_make_main([_MAC], clients=[{"mac": _MAC}])))[0]
    assert tracker.name == _MAC


async def test_allowlist_limits_tracked_clients(setup):
    """Only associated clients on the allowlist get a tracker."""
    added = await setup(_make_main([_MAC, _OTHER_MAC]), tracked=[_MAC])
    assert [e._mac for e in added] == [_MAC]


async def test_empty_allowlist_tracks_nothing(setup):
    """Empty allowlist is opt-in inert — no trackers even with clients present."""
    added = await setup(_make_main([_MAC, _OTHER_MAC]), tracked=[])
    assert added == []


async def test_no_duplicate_trackers_on_repeated_updates(setup):
    added = await setup(_make_main([_MAC]))
    added[0].coordinator.async_set_updated_data({_MAC})
    assert len(added) == 1
