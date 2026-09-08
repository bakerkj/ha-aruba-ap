# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Device tracker platform for Aruba Instant AP (opt-in presence detection).

A separate, lightweight ``ArubaPresenceCoordinator`` polls only the
associated-client table on a fast cadence, so presence is responsive without
polling the full AP telemetry (and its recorder writes) that often. Each
associated client becomes a modern ``ScannerEntity`` — API/SNMP based, so none
of the fork-per-scan cost of the legacy telnet ``aruba`` device_tracker.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_PRESENCE_INTERVAL, DEFAULT_PRESENCE_INTERVAL, DOMAIN
from .sensor import ArubaAPCoordinator

_LOGGER = logging.getLogger(__name__)


class ArubaPresenceCoordinator(DataUpdateCoordinator[set[str]]):
    """Fast, presence-only coordinator: the set of currently associated MACs."""

    def __init__(
        self, hass: HomeAssistant, main: ArubaAPCoordinator, interval: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{main.name} presence",
            update_interval=timedelta(seconds=max(10, interval)),
        )
        self.main = main

    async def _async_update_data(self) -> set[str]:
        try:
            return await self.main.async_present_client_macs()
        except Exception as err:
            raise UpdateFailed(str(err)) from err


class ArubaClientTracker(CoordinatorEntity[ArubaPresenceCoordinator], ScannerEntity):
    """Presence of one WiFi client, from the AP's associated-station table.

    A ``ScannerEntity`` keys itself by ``mac_address`` (its unique_id) and
    creates no device of its own — HA links it to whichever device already
    carries that MAC connection, i.e. the client device the sensor platform
    registered. ``name``/``hostname``/``ip`` are read best-effort from the full
    telemetry coordinator and refreshed on each presence update.
    """

    _attr_source_type = SourceType.ROUTER

    def __init__(
        self,
        coordinator: ArubaPresenceCoordinator,
        main: ArubaAPCoordinator,
        entry_id: str,
        mac: str,
    ) -> None:
        super().__init__(coordinator)
        self._main = main
        self._mac = mac
        self._attr_mac_address = mac
        self._refresh_client_attrs()

    def _client(self) -> dict[str, Any] | None:
        """Best-effort lookup of this MAC in the full coordinator's client data."""
        data = self._main.data
        if data is None:
            return None
        return next((c for c in data.clients if c["mac"] == self._mac), None)

    def _refresh_client_attrs(self) -> None:
        client = self._client()
        name = client.get("name") if client else None
        self._attr_name = name or self._mac
        self._attr_hostname = name
        self._attr_ip_address = client.get("ip") if client else None

    @property
    def is_connected(self) -> bool:
        return self._mac in (self.coordinator.data or set())

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_client_attrs()
        super()._handle_coordinator_update()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one presence tracker per associated WiFi client."""
    main: ArubaAPCoordinator = hass.data[DOMAIN][entry.entry_id]
    interval = entry.options.get(CONF_PRESENCE_INTERVAL, DEFAULT_PRESENCE_INTERVAL)
    presence = ArubaPresenceCoordinator(hass, main, interval)
    entry_id = entry.entry_id
    known: set[str] = set()

    @callback
    def _add_new_trackers() -> None:
        macs = presence.data
        if not macs:
            return
        if main.clients_mapped_only:
            macs = macs & main._mac_hostname_map.keys()
        new = macs - known
        if not new:
            return
        known.update(new)
        async_add_entities(
            ArubaClientTracker(presence, main, entry_id, mac) for mac in new
        )

    # Adding the listener schedules the periodic poll; the immediate refresh
    # populates the first set of trackers. A presence-poll failure must not fail
    # the platform (the telemetry entry is independent), so refresh rather than
    # first-refresh — trackers simply appear on the next successful poll.
    entry.async_on_unload(presence.async_add_listener(_add_new_trackers))
    await presence.async_refresh()
