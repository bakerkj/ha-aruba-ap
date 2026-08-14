# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Shared entity plumbing for the Aruba Instant AP platforms."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

if TYPE_CHECKING:
    from .sensor import ArubaAPCoordinator


class ArubaEntityMixin(Entity):
    """Coordinator subscription shared by every Aruba platform.

    The coordinator is held directly rather than via ``CoordinatorEntity`` so
    entities can decide for themselves what an absent client means — a sensor
    goes unavailable, a connectivity binary sensor goes ``off``.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: ArubaAPCoordinator) -> None:
        self.coordinator = coordinator
        self._unsub: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub is not None:
            self._unsub()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
