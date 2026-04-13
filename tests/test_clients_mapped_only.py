# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for the clients_mapped_only option.

When clients_mapped_only=True, async_setup_entry should only create entities
for client MACs that appear in the coordinator's _mac_hostname_map.  Clients
absent from the map must be silently skipped.
"""

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aruba_instant_ap.const import DOMAIN
from custom_components.aruba_instant_ap.sensor import (
    CLIENT_SENSOR_DESCRIPTIONS,
    ClientSensor,
    async_setup_entry,
)

_MAPPED_MAC = "aa:bb:cc:11:11:11"
_UNMAPPED_MAC = "aa:bb:cc:22:22:22"


def _make_coordinator(clients_mapped_only: bool, mac_map: dict) -> MagicMock:
    """Return a minimal coordinator mock for async_setup_entry."""
    coord = MagicMock()
    coord.clients_mapped_only = clients_mapped_only
    coord._mac_hostname_map = mac_map
    coord.data.aps = {}
    coord.data.clients = [
        {"mac": _MAPPED_MAC},
        {"mac": _UNMAPPED_MAC},
    ]
    # async_add_listener must return a callable (used as unsubscribe)
    coord.async_add_listener.return_value = lambda: None
    return coord


async def _setup(hass, coordinator) -> list[ClientSensor]:
    """Run async_setup_entry and return the ClientSensor entities that were added."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})["test_entry"] = coordinator

    added: list = []

    def capture(entities, *_args, **_kwargs):
        added.extend(entities)

    await async_setup_entry(hass, entry, capture)
    return [e for e in added if isinstance(e, ClientSensor)]


# ── clients_mapped_only=False (default) ───────────────────────────────────────


async def test_all_clients_created_when_option_off(hass):
    """With clients_mapped_only=False all clients get entities regardless of map."""
    coord = _make_coordinator(clients_mapped_only=False, mac_map={_MAPPED_MAC: "Known"})
    clients = await _setup(hass, coord)
    macs = {e._mac for e in clients}
    assert _MAPPED_MAC in macs
    assert _UNMAPPED_MAC in macs


async def test_all_clients_created_when_map_empty_and_option_off(hass):
    """With clients_mapped_only=False an empty map still creates all clients."""
    coord = _make_coordinator(clients_mapped_only=False, mac_map={})
    clients = await _setup(hass, coord)
    macs = {e._mac for e in clients}
    assert _MAPPED_MAC in macs
    assert _UNMAPPED_MAC in macs


# ── clients_mapped_only=True ──────────────────────────────────────────────────


async def test_only_mapped_clients_created_when_option_on(hass):
    """With clients_mapped_only=True only MACs in the map get entities."""
    coord = _make_coordinator(clients_mapped_only=True, mac_map={_MAPPED_MAC: "Known"})
    clients = await _setup(hass, coord)
    macs = {e._mac for e in clients}
    assert _MAPPED_MAC in macs
    assert _UNMAPPED_MAC not in macs


async def test_no_clients_created_when_map_empty_and_option_on(hass):
    """With clients_mapped_only=True and an empty map no client entities are created."""
    coord = _make_coordinator(clients_mapped_only=True, mac_map={})
    clients = await _setup(hass, coord)
    assert clients == []


async def test_correct_number_of_entities_per_mapped_client(hass):
    """Each mapped client gets one entity per CLIENT_SENSOR_DESCRIPTIONS entry."""
    coord = _make_coordinator(clients_mapped_only=True, mac_map={_MAPPED_MAC: "Known"})
    clients = await _setup(hass, coord)
    mapped_entities = [e for e in clients if e._mac == _MAPPED_MAC]
    assert len(mapped_entities) == len(CLIENT_SENSOR_DESCRIPTIONS)


async def test_all_clients_create_correct_entity_count_when_option_off(hass):
    """With option off, both clients get the full set of entities."""
    coord = _make_coordinator(clients_mapped_only=False, mac_map={})
    clients = await _setup(hass, coord)
    assert len(clients) == 2 * len(CLIENT_SENSOR_DESCRIPTIONS)
