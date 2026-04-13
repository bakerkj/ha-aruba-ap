# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests that verify enabling and disabling entities works via the HA entity registry.

These tests use a live HomeAssistant instance (via the hass fixture) to confirm:
  - Entities with enabled_default=False are absent from the state machine on setup.
  - Entities with enabled_default=True are present in the state machine on setup.
  - A disabled entity can be re-enabled via the entity registry.
  - An enabled entity can be disabled via the entity registry.
"""

import logging
from datetime import timedelta
from unittest.mock import MagicMock

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import EntityComponent

from custom_components.aruba_instant_ap.sensor import (
    APSensor,
    APSensorDescription,
    ClientSensor,
    ClientSensorDescription,
)

_LOGGER = logging.getLogger(__name__)
_DOMAIN = "sensor"


def _make_coordinator() -> MagicMock:
    coord = MagicMock()
    ap = MagicMock()
    ap.name = "Test AP"
    ap.model = None
    ap.firmware = None
    ap.serial = None
    ap.radios = {}
    coord.data.aps.get.return_value = ap
    coord.data.clients = []
    return coord


async def _platform(hass) -> EntityComponent:
    return EntityComponent(_LOGGER, _DOMAIN, hass, timedelta(seconds=30))


# ── Disabled by default: not in state machine ─────────────────────────────────


async def test_disabled_entity_absent_from_state_machine(hass):
    component = await _platform(hass)
    desc = APSensorDescription(
        key="dis_test",
        name="Disabled Test",
        value_fn=lambda ap: "val",
        enabled_default=False,
    )
    entity = APSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", desc)
    await component.async_add_entities([entity])

    assert hass.states.get(entity.entity_id) is None


async def test_disabled_entity_registered_as_disabled(hass):
    component = await _platform(hass)
    desc = APSensorDescription(
        key="dis_reg_test",
        name="Disabled Reg Test",
        value_fn=lambda ap: "val",
        enabled_default=False,
    )
    entity = APSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", desc)
    await component.async_add_entities([entity])

    registry = er.async_get(hass)
    entry = registry.async_get(entity.entity_id)
    assert entry is not None
    assert entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION


# ── Enabled by default: present in state machine ──────────────────────────────


async def test_enabled_entity_present_in_state_machine(hass):
    component = await _platform(hass)
    desc = APSensorDescription(
        key="en_test",
        name="Enabled Test",
        value_fn=lambda ap: "val",
        enabled_default=True,
    )
    entity = APSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", desc)
    await component.async_add_entities([entity])

    assert hass.states.get(entity.entity_id) is not None


async def test_enabled_entity_not_disabled_in_registry(hass):
    component = await _platform(hass)
    desc = APSensorDescription(
        key="en_reg_test",
        name="Enabled Reg Test",
        value_fn=lambda ap: "val",
        enabled_default=True,
    )
    entity = APSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", desc)
    await component.async_add_entities([entity])

    registry = er.async_get(hass)
    entry = registry.async_get(entity.entity_id)
    assert entry is None or entry.disabled_by is None


# ── Re-enabling a disabled entity removes the disabled_by flag ────────────────


async def test_enabling_disabled_entity_clears_disabled_by(hass):
    component = await _platform(hass)
    desc = ClientSensorDescription(
        key="reenable_test",
        name="Re-enable Test",
        value_fn=lambda c: "val",
        enabled_default=False,
    )
    entity = ClientSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", desc)
    await component.async_add_entities([entity])

    registry = er.async_get(hass)
    entry = registry.async_get(entity.entity_id)
    assert entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION

    registry.async_update_entity(entity.entity_id, disabled_by=None)

    updated = registry.async_get(entity.entity_id)
    assert updated.disabled_by is None


# ── Disabling an enabled entity sets the disabled_by flag ─────────────────────


async def test_disabling_enabled_entity_sets_disabled_by(hass):
    component = await _platform(hass)
    desc = ClientSensorDescription(
        key="disable_test",
        name="Disable Test",
        value_fn=lambda c: "val",
        enabled_default=True,
    )
    entity = ClientSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", desc)
    await component.async_add_entities([entity])

    assert hass.states.get(entity.entity_id) is not None

    registry = er.async_get(hass)
    registry.async_update_entity(
        entity.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )

    updated = registry.async_get(entity.entity_id)
    assert updated.disabled_by == er.RegistryEntryDisabler.USER
