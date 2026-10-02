# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for entry setup/unload platform handling."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.aruba_instant_ap as aruba
from custom_components.aruba_instant_ap.const import (
    CONF_COMMUNITY,
    CONF_ENABLE_DEVICE_TRACKER,
    CONF_HOST,
    DOMAIN,
)


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
    coordinator = MagicMock()
    coordinator.async_shutdown = AsyncMock()
    hass.data.setdefault(DOMAIN, {})["e1"] = coordinator

    with patch.object(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    ) as mock_unload:
        assert await aruba.async_unload_entry(hass, entry)

    mock_unload.assert_awaited_once_with(
        entry, [Platform.BINARY_SENSOR, Platform.SENSOR]
    )
    coordinator.async_shutdown.assert_awaited_once()  # refresh + flush stopped
    assert "e1" not in aruba._FORWARDED


async def _setup_entry_with_mocks(
    hass, entry: MockConfigEntry, *, tracker_enabled: bool
) -> None:
    """Drive ``aruba.async_setup_entry`` with the SNMP coordinator + prewarm
    + platform forwards all mocked out, so the test can focus on the entry's
    own control flow (specifically, whether purge_stranded_trackers fires on
    the feature-disabled path)."""
    coord = MagicMock()
    coord.async_config_entry_first_refresh = AsyncMock()
    with (
        patch.object(aruba, "ArubaAPCoordinator", return_value=coord),
        patch.object(aruba, "async_prewarm_plugins", AsyncMock()),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await aruba.async_setup_entry(hass, entry)


async def test_setup_purges_stranded_when_tracker_disabled(hass):
    """Toggling CONF_ENABLE_DEVICE_TRACKER off triggers a reload. The next
    setup won't forward Platform.DEVICE_TRACKER, so the platform's own
    async_setup_entry (where the purge normally runs) never fires. The entry
    must purge any previously-registered trackers itself; otherwise every
    tracker from the enabled era is stranded forever as a stale ``restored``
    unavailable entity."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="disabled_entry",
        data={CONF_HOST: "ap.example", CONF_COMMUNITY: "public"},
        options={CONF_ENABLE_DEVICE_TRACKER: False},
    )
    entry.add_to_hass(hass)
    # Pre-register a tracker as if a prior setup (with the feature enabled)
    # had created it.
    reg = er.async_get(hass)
    stale = reg.async_get_or_create(
        domain=Platform.DEVICE_TRACKER,
        platform=DOMAIN,
        unique_id="40:2f:86:40:5e:86",
        config_entry=entry,
    )
    assert reg.async_get(stale.entity_id) is not None

    await _setup_entry_with_mocks(hass, entry, tracker_enabled=False)

    assert reg.async_get(stale.entity_id) is None
    aruba._FORWARDED.pop(entry.entry_id, None)


async def test_setup_leaves_registry_alone_when_tracker_enabled(hass):
    """When the device_tracker platform IS forwarded, ``__init__`` must NOT
    purge; the platform's own ``async_setup_entry`` owns that pass. A
    pre-registered tracker for a MAC still in the allowlist stays put."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="enabled_entry",
        data={CONF_HOST: "ap.example", CONF_COMMUNITY: "public"},
        options={CONF_ENABLE_DEVICE_TRACKER: True},
    )
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    kept = reg.async_get_or_create(
        domain=Platform.DEVICE_TRACKER,
        platform=DOMAIN,
        unique_id="40:2f:86:40:5e:86",
        config_entry=entry,
    )

    await _setup_entry_with_mocks(hass, entry, tracker_enabled=True)

    assert reg.async_get(kept.entity_id) is not None
    aruba._FORWARDED.pop(entry.entry_id, None)
