# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for entry setup/unload platform handling."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import Platform
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.aruba_instant_ap as aruba
from custom_components.aruba_instant_ap.const import CONF_ENABLE_DEVICE_TRACKER, DOMAIN


async def test_unload_uses_forwarded_platforms_not_current_options(hass):
    """Unload the platforms the prior setup forwarded, not a list recomputed from
    (possibly changed) options. Enabling device_tracker flips the option and
    reloads; unloading a device_tracker platform the disabled setup never created
    crashed HA's component and left the entry FAILED_UNLOAD."""
    entry = MockConfigEntry(
        domain=DOMAIN, entry_id="e1", options={CONF_ENABLE_DEVICE_TRACKER: True}
    )
    entry.add_to_hass(hass)
    # prior setup ran while the tracker was disabled → only these were forwarded
    aruba._FORWARDED["e1"] = [Platform.BINARY_SENSOR, Platform.SENSOR]
    hass.data.setdefault(DOMAIN, {})["e1"] = MagicMock()

    with patch.object(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    ) as mock_unload:
        assert await aruba.async_unload_entry(hass, entry)

    mock_unload.assert_awaited_once_with(
        entry, [Platform.BINARY_SENSOR, Platform.SENSOR]
    )
    assert "e1" not in aruba._FORWARDED
