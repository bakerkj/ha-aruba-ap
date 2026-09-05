# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Binary sensor platform for Aruba Instant AP."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN
from .entity import ArubaEntityMixin
from .sensor import (
    ArubaAPCoordinator,
    _client_display_name,
    _mac_slug,
    client_device_info,
)

_LOGGER = logging.getLogger(__name__)


class ClientConnectivity(ArubaEntityMixin, BinarySensorEntity):
    """Whether the AP cluster currently sees this client associated.

    Unlike the client sensors, an absent client is ``off`` rather than
    unavailable: "gone from the wireless network" is the reading, not a
    missing one. Only a failed poll makes this unavailable, so the state
    never claims a client left when it was the APs that stopped answering.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Connected"

    def __init__(
        self, coordinator: ArubaAPCoordinator, entry_id: str, mac: str
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._entry_id = entry_id
        mac_slug = _mac_slug(mac)
        self._attr_unique_id = f"{entry_id}_client_{mac_slug}_connected"
        client = self._find_client(coordinator)
        name = client.get("name") if client else None
        if name:
            self.entity_id = f"binary_sensor.{slugify(name)}_connected"
        else:
            self.entity_id = f"binary_sensor.client_{mac_slug}_connected"
        # The radio link (via_device_id) is maintained by ClientSensor's
        # reconciler on the shared client device; this binary sensor only needs
        # the identity fields.
        self._attr_device_info = client_device_info(
            entry_id,
            mac,
            _client_display_name(client, mac),
        )

    def _find_client(
        self, coordinator: ArubaAPCoordinator | None = None
    ) -> dict[str, Any] | None:
        coord = coordinator or self.coordinator
        if not coord.data:
            return None
        return next((c for c in coord.data.clients if c["mac"] == self._mac), None)

    @property
    def is_on(self) -> bool:
        return self._find_client() is not None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one connectivity binary sensor per WiFi client."""
    coordinator: ArubaAPCoordinator = hass.data[DOMAIN][entry.entry_id]
    entry_id = entry.entry_id
    known_client_macs: set[str] = set()

    @callback
    def _add_new_clients() -> None:
        if not coordinator.data:
            return
        current_macs = {c["mac"] for c in coordinator.data.clients}
        if coordinator.clients_mapped_only:
            current_macs = current_macs & coordinator._mac_hostname_map.keys()
        new_macs = current_macs - known_client_macs
        if not new_macs:
            return
        known_client_macs.update(new_macs)
        async_add_entities(
            ClientConnectivity(coordinator, entry_id, mac) for mac in new_macs
        )

    _add_new_clients()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_clients))
