# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for the per-client connectivity binary sensor and the MAC connection.

Together these let another integration's view of the same hardware share the
device: the MAC is the key the registry matches on, and the binary sensor is
the on/off reading a monitor can act upon.
"""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aruba_instant_ap.binary_sensor import (
    ClientConnectivity,
    async_setup_entry,
)
from custom_components.aruba_instant_ap.const import DOMAIN
from custom_components.aruba_instant_ap.sensor import (
    CLIENT_SENSOR_DESCRIPTIONS,
    ClientSensor,
)

_MAC = "40:2f:86:40:5e:86"
_OTHER_MAC = "24:e8:53:6c:8c:90"


def _make_coordinator(clients: list[dict] | None = None) -> MagicMock:
    coord = MagicMock()
    coord.clients_mapped_only = False
    coord._mac_hostname_map = {}
    coord.last_update_success = True
    coord.data.clients = (
        [{"mac": _MAC, "name": "lg-washer"}] if clients is None else clients
    )
    coord.async_add_listener.return_value = lambda: None
    return coord


async def _setup(hass, coordinator) -> list[ClientConnectivity]:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    added: list = []

    def capture(entities, *_args, **_kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, capture)
    return added


# ── the binary sensor ────────────────────────────────────────────────────────


async def test_one_connectivity_sensor_per_client(hass):
    """Each client gets exactly one connectivity entity."""
    coord = _make_coordinator(
        [{"mac": _MAC, "name": "lg-washer"}, {"mac": _OTHER_MAC, "name": "lg-dehum"}]
    )
    added = await _setup(hass, coord)
    assert len(added) == 2
    assert {e._mac for e in added} == {_MAC, _OTHER_MAC}
    assert all(e.device_class is BinarySensorDeviceClass.CONNECTIVITY for e in added)


async def test_on_while_the_client_is_associated(hass):
    """A client the cluster reports is on."""
    coord = _make_coordinator()
    entity = (await _setup(hass, coord))[0]
    assert entity.is_on is True
    assert entity.available is True


async def test_off_once_the_client_leaves(hass):
    """A client that drops off the wireless network reads off, not unavailable —
    that distinction is the whole signal."""
    coord = _make_coordinator()
    entity = (await _setup(hass, coord))[0]
    coord.data.clients = []
    assert entity.is_on is False
    assert entity.available is True


async def test_unavailable_when_the_poll_fails(hass):
    """A failed SNMP poll must not read as "every client left"."""
    coord = _make_coordinator()
    entity = (await _setup(hass, coord))[0]
    coord.last_update_success = False
    assert entity.available is False


async def test_entity_id_follows_the_client_name(hass):
    coord = _make_coordinator()
    entity = (await _setup(hass, coord))[0]
    assert entity.entity_id == "binary_sensor.lg_washer_connected"
    assert entity.unique_id == "test_entry_client_402f86405e86_connected"


async def test_entity_id_falls_back_to_the_mac(hass):
    coord = _make_coordinator([{"mac": _MAC}])
    entity = (await _setup(hass, coord))[0]
    assert entity.entity_id == "binary_sensor.client_402f86405e86_connected"


async def test_clients_mapped_only_is_honoured(hass):
    """The option that filters the sensor platform filters this one too."""
    coord = _make_coordinator(
        [{"mac": _MAC, "name": "lg-washer"}, {"mac": _OTHER_MAC, "name": "lg-dehum"}]
    )
    coord.clients_mapped_only = True
    coord._mac_hostname_map = {_MAC: "lg-washer"}
    added = await _setup(hass, coord)
    assert [e._mac for e in added] == [_MAC]


async def test_no_duplicates_on_repeated_coordinator_updates(hass):
    """The listener adds only clients it has not already seen."""
    coord = _make_coordinator()
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})["test_entry"] = coord

    added: list = []
    coord.async_add_listener.side_effect = lambda cb: cb or (lambda: None)
    await async_setup_entry(hass, entry, lambda es, *a, **k: added.extend(es))
    listener = coord.async_add_listener.call_args[0][0]
    listener()
    listener()
    assert len(added) == 1


# ── the MAC connection ───────────────────────────────────────────────────────


async def test_client_device_carries_the_mac_connection(hass):
    """Both platforms describe the client device with its MAC in connections."""
    coord = _make_coordinator()
    binary = (await _setup(hass, coord))[0]
    sensor = ClientSensor(coord, "test_entry", _MAC, CLIENT_SENSOR_DESCRIPTIONS[0])
    expected = {(dr.CONNECTION_NETWORK_MAC, _MAC)}
    assert binary.device_info["connections"] == expected
    assert sensor.device_info["connections"] == expected
    assert (
        binary.device_info["identifiers"]
        == sensor.device_info["identifiers"]
        == {(DOMAIN, "test_entry_client_402f86405e86")}
    )


async def _register_beside_an_existing_device(hass):
    """Register our client device where another integration already claimed the
    MAC. Returns (theirs, ours)."""
    reg = dr.async_get(hass)
    other = MockConfigEntry(domain="smartthinq_sensors")
    other.add_to_hass(hass)
    theirs = reg.async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("smartthinq_sensors", "appliance-uuid")},
        connections={(dr.CONNECTION_NETWORK_MAC, _MAC)},
    )
    ours_entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    ours_entry.add_to_hass(hass)
    binary = (await _setup(hass, _make_coordinator()))[0]
    ours = reg.async_get_or_create(
        config_entry_id=ours_entry.entry_id, **binary.device_info
    )
    return theirs, ours


# HA 2026.8 stopped merging devices across config entries: a device is one
# entry's view of a thing. The MAC is worth publishing either way — before the
# split it shares the row, after it, it is the key that rejoins the two.
_SPLIT_REGISTRY = hasattr(dr.DeviceEntry, "config_entry_id")


@pytest.mark.skipif(_SPLIT_REGISTRY, reason="2026.8+ keeps the views separate")
async def test_mac_connection_merges_into_an_existing_device(hass):
    """Below 2026.8 the registry merges on the connection, so the client's
    entities land on the device that already represents the hardware."""
    theirs, ours = await _register_beside_an_existing_device(hass)
    assert ours.id == theirs.id
    assert ("smartthinq_sensors", "appliance-uuid") in ours.identifiers


@pytest.mark.skipif(not _SPLIT_REGISTRY, reason="pre-2026.8 merges instead")
async def test_mac_connection_is_the_key_that_rejoins_after_the_split(hass):
    """From 2026.8 the two views stay separate — but both carry the MAC, which
    is what lets a consumer pair them back up."""
    theirs, ours = await _register_beside_an_existing_device(hass)
    assert ours.id != theirs.id
    mac = (dr.CONNECTION_NETWORK_MAC, _MAC)
    assert mac in ours.connections
    assert mac in theirs.connections
