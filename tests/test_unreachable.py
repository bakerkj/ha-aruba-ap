# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for handling a controller that does not answer SNMP."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.aruba_instant_ap as aruba
from custom_components.aruba_instant_ap.const import (
    CONF_COMMUNITY,
    CONF_HOST,
    DOMAIN,
    OID_AP_NAME,
    OID_SYS_NAME,
)
from custom_components.aruba_instant_ap.sensor import ArubaAPCoordinator


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="unreachable",
        data={CONF_HOST: "ap.example", CONF_COMMUNITY: "public"},
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_not_ready_when_controller_does_not_answer(hass):
    """No SNMP answer: setup raises ConfigEntryNotReady before building anything."""
    entry = _entry(hass)
    coordinator_cls = MagicMock()
    forward = AsyncMock()
    with (
        patch.object(aruba, "async_prewarm_plugins", AsyncMock()),
        patch.object(aruba, "async_snmp_get", AsyncMock(return_value=None)) as probe,
        patch.object(aruba, "ArubaAPCoordinator", coordinator_cls),
        patch.object(hass.config_entries, "async_forward_entry_setups", forward),
        pytest.raises(ConfigEntryNotReady),
    ):
        await aruba.async_setup_entry(hass, entry)

    args, kwargs = probe.call_args
    assert args == ("ap.example", "public", 161, OID_SYS_NAME)
    assert kwargs["timeout"] == aruba.REACHABILITY_TIMEOUT_S
    assert kwargs["retries"] == aruba.REACHABILITY_RETRIES
    coordinator_cls.assert_not_called()
    forward.assert_not_awaited()
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    assert entry.entry_id not in aruba._FORWARDED


async def test_update_fails_when_every_walk_is_empty(hass):
    """A poll where every walk comes back empty is a failed update, not data."""
    coord = ArubaAPCoordinator(hass, "host", "public", 161, "2c", 30)
    with (
        patch.object(coord, "_walk", AsyncMock(return_value={})),
        pytest.raises(UpdateFailed, match="No SNMP data from host"),
    ):
        await coord._async_update_data()


async def test_update_succeeds_when_some_walks_answer(hass):
    """One walk with data is enough: a partial answer is still an update."""
    coord = ArubaAPCoordinator(hass, "host", "public", 161, "2c", 30)

    async def _walk(oid: str) -> dict[str, str]:
        if oid == OID_AP_NAME:
            return {f"{OID_AP_NAME}.64.47.134.64.94.134": "ap-1"}
        return {}

    with patch.object(coord, "_walk", _walk):
        data = await coord._async_update_data()

    assert data is not None
