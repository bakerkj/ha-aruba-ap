# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Aruba Instant AP HASS integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_COMMUNITY,
    CONF_HOST,
    CONF_MAC_HOSTNAME_FILE,
    CONF_SNMP_PORT,
    DEFAULT_SNMP_PORT,
    DOMAIN,
)
from .sensor import ArubaAPCoordinator
from .snmp_helper import async_prewarm_plugins

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Aruba Instant AP from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    host = entry.data[CONF_HOST]
    community = entry.data[CONF_COMMUNITY]
    snmp_port = entry.data.get(CONF_SNMP_PORT, DEFAULT_SNMP_PORT)
    snmp_version = entry.options.get("snmp_version", "v2c")
    update_seconds = max(10, entry.options.get("update_interval", 30))
    mac_hostname_file = entry.options.get(CONF_MAC_HOSTNAME_FILE, "")

    coordinator = ArubaAPCoordinator(
        hass,
        host,
        community,
        snmp_port,
        snmp_version,
        update_seconds,
        mac_hostname_file,
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await async_prewarm_plugins(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
