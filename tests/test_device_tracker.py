# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for the opt-in presence device_tracker.

A lightweight coordinator polls only the associated-client set; each allowlisted
MAC gets a router ScannerEntity up front — home while the cluster reports it,
not_home otherwise, unavailable when the poll fails.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.device_tracker import SourceType
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
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

    async def _do(main, tracked=(_MAC,)) -> list[ArubaClientTracker]:
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


async def test_one_tracker_per_tracked_client(setup):
    added = await setup(_make_main([_MAC, _OTHER_MAC]), tracked=[_MAC, _OTHER_MAC])
    assert {e._mac for e in added} == {_MAC, _OTHER_MAC}
    assert all(e.source_type is SourceType.ROUTER for e in added)
    assert all(e.mac_address == e._mac for e in added)
    # ScannerEntity keys itself by MAC
    assert {e.unique_id for e in added} == {_MAC, _OTHER_MAC}


async def test_home_while_associated(setup):
    tracker = (await setup(_make_main([_MAC]), tracked=[_MAC]))[0]
    assert tracker.is_connected is True
    assert tracker.available is True


async def test_tracked_but_absent_is_created_not_home(setup):
    """A tracked client that isn't associated still gets a tracker (not_home),
    so arrival automations have a prior state to transition from."""
    added = await setup(_make_main([]), tracked=[_MAC])
    assert [e._mac for e in added] == [_MAC]
    assert added[0].is_connected is False
    assert added[0].available is True  # poll succeeded, just not present


async def test_not_home_once_it_leaves(setup):
    """A client no longer in the associated set reads not-connected (its poll
    still succeeded), never unavailable — that distinction is the signal."""
    tracker = (await setup(_make_main([_MAC]), tracked=[_MAC]))[0]
    tracker.coordinator.data.discard(_MAC)
    assert tracker.is_connected is False
    assert tracker.available is True


async def test_unavailable_when_presence_poll_fails(setup):
    tracker = (await setup(_make_main([_MAC]), tracked=[_MAC]))[0]
    tracker.coordinator.last_update_success = False
    assert tracker.available is False


async def test_name_and_ip_follow_the_client(setup):
    tracker = (await setup(_make_main([_MAC]), tracked=[_MAC]))[0]
    assert tracker.name == "lg-washer"
    assert tracker.hostname == "lg-washer"
    assert tracker.ip_address == "192.168.1.5"


async def test_name_falls_back_to_mac(setup):
    tracker = (
        await setup(_make_main([_MAC], clients=[{"mac": _MAC}]), tracked=[_MAC])
    )[0]
    assert tracker.name == _MAC


async def test_mac_casing_is_normalized(setup):
    """An allowlist MAC in upper case still matches the lower-case AP table."""
    tracker = (await setup(_make_main([_MAC]), tracked=[_MAC.upper()]))[0]
    assert tracker.mac_address == _MAC  # canonical lower case
    assert tracker.is_connected is True


async def test_allowlist_limits_tracked_clients(setup):
    """Only clients on the allowlist get a tracker, regardless of who's present."""
    added = await setup(_make_main([_MAC, _OTHER_MAC]), tracked=[_MAC])
    assert [e._mac for e in added] == [_MAC]


async def test_empty_allowlist_tracks_nothing(setup):
    """Empty allowlist is opt-in inert — no trackers even with clients present."""
    added = await setup(_make_main([_MAC, _OTHER_MAC]), tracked=[])
    assert added == []


async def test_trackers_created_once_at_setup(setup):
    added = await setup(_make_main([_MAC]), tracked=[_MAC])
    added[0].coordinator.async_set_updated_data({_MAC})
    assert len(added) == 1


# ── Registry cleanup: stranded entities get purged on setup ──────────────────
#
# ``async_setup_entry`` only creates entities for the current allowlist. A MAC
# that was once allowlisted and has since been removed from the option leaves
# its registration behind. HA core restores that entity from storage on next
# start, nothing drives its state, and it sits as ``unavailable`` forever. The
# purge pass before the early-exit catches that.


async def _preregister_tracker(hass, config_entry, mac: str) -> str:
    """Register a device_tracker in the registry as if a previous setup had
    created it, but without instantiating an entity. Returns the entity_id."""
    reg = er.async_get(hass)
    entry = reg.async_get_or_create(
        domain=Platform.DEVICE_TRACKER,
        platform=DOMAIN,
        unique_id=mac,
        config_entry=config_entry,
    )
    return entry.entity_id


async def test_stranded_tracker_removed_on_setup(hass, setup):
    """A device_tracker whose MAC is no longer in the allowlist is purged from
    the entity registry on setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="purge_entry",
        options={CONF_TRACKED_CLIENTS: [_MAC]},
    )
    entry.add_to_hass(hass)
    stale_eid = await _preregister_tracker(hass, entry, _OTHER_MAC)
    reg = er.async_get(hass)
    assert reg.async_get(stale_eid) is not None

    main = _make_main([_MAC])
    hass.data.setdefault(DOMAIN, {})["purge_entry"] = main
    added: list = []
    await async_setup_entry(hass, entry, lambda es, *_a, **_k: added.extend(es))
    try:
        assert reg.async_get(stale_eid) is None
        assert {e._mac for e in added} == {_MAC}
    finally:
        if added:
            await added[0].coordinator.async_shutdown()


async def test_tracker_kept_when_still_in_allowlist(hass, setup):
    """A device_tracker whose MAC is still in the current allowlist stays
    put -- the purge removes only MACs that have left the allowlist."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="keep_entry",
        options={CONF_TRACKED_CLIENTS: [_MAC]},
    )
    entry.add_to_hass(hass)
    kept_eid = await _preregister_tracker(hass, entry, _MAC)
    reg = er.async_get(hass)

    main = _make_main([_MAC])
    hass.data.setdefault(DOMAIN, {})["keep_entry"] = main
    added: list = []
    await async_setup_entry(hass, entry, lambda es, *_a, **_k: added.extend(es))
    try:
        assert reg.async_get(kept_eid) is not None
    finally:
        if added:
            await added[0].coordinator.async_shutdown()


async def test_empty_allowlist_still_purges_stranded(hass):
    """Emptying the allowlist entirely must still purge every prior
    registration -- the early-exit for ``not tracked`` runs AFTER the purge
    so 'remove everything' leaves nothing behind, instead of marooning every
    former tracker as ``unavailable``."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="empty_entry",
        options={CONF_TRACKED_CLIENTS: []},
    )
    entry.add_to_hass(hass)
    stale_a = await _preregister_tracker(hass, entry, _MAC)
    stale_b = await _preregister_tracker(hass, entry, _OTHER_MAC)
    reg = er.async_get(hass)

    main = _make_main([])
    hass.data.setdefault(DOMAIN, {})["empty_entry"] = main
    added: list = []
    await async_setup_entry(hass, entry, lambda es, *_a, **_k: added.extend(es))
    assert added == []
    assert reg.async_get(stale_a) is None
    assert reg.async_get(stale_b) is None


async def test_purge_scoped_to_own_platform_and_entry(hass):
    """The purge only touches device_tracker entities whose platform is this
    integration AND whose config_entry is the one being set up. A sensor on
    the same entry, and a device_tracker from a different integration on a
    different entry, both survive."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="scope_entry",
        options={CONF_TRACKED_CLIENTS: [_MAC]},
    )
    entry.add_to_hass(hass)
    foreign_entry = MockConfigEntry(domain="foreign_domain", entry_id="foreign_entry")
    foreign_entry.add_to_hass(hass)

    reg = er.async_get(hass)
    # Sensor on this integration's entry: survives (wrong domain).
    sensor_eid = reg.async_get_or_create(
        domain="sensor",
        platform=DOMAIN,
        unique_id=f"{_OTHER_MAC}_signal",
        config_entry=entry,
    ).entity_id
    # device_tracker owned by a different integration: survives (wrong platform
    # AND wrong config_entry).
    foreign_eid = reg.async_get_or_create(
        domain=Platform.DEVICE_TRACKER,
        platform="foreign_domain",
        unique_id=_OTHER_MAC,
        config_entry=foreign_entry,
    ).entity_id

    main = _make_main([_MAC])
    hass.data.setdefault(DOMAIN, {})["scope_entry"] = main
    added: list = []
    await async_setup_entry(hass, entry, lambda es, *_a, **_k: added.extend(es))
    try:
        assert reg.async_get(sensor_eid) is not None
        assert reg.async_get(foreign_eid) is not None
    finally:
        if added:
            await added[0].coordinator.async_shutdown()
