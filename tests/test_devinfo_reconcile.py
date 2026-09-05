# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Regression tests for _DeviceInfoReconciler resubscription after removal.

Previously a device removal cleared only ``_device_id`` while ``_unsub_devreg``
kept the listener for the gone device; ``_ensure_devreg_subscription``'s
``if self._unsub_devreg is None`` guard then never re-subscribed, so a device
recreated under the same identifier was tracked but its external edits/removals
were never detected again. Removal must tear the subscription down too.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aruba_instant_ap.const import DOMAIN
from custom_components.aruba_instant_ap.sensor import (
    AP_SENSOR_DESCRIPTIONS,
    APSensor,
    _mac_slug,
)

_AP_MAC = "d0:d3:e0:c6:53:46"


def _coord() -> Any:
    return SimpleNamespace(
        data=SimpleNamespace(
            aps={
                _AP_MAC: SimpleNamespace(
                    name="1st Living", model="515", firmware="8.13", serial="XYZ"
                )
            }
        ),
        last_update_success=True,
    )


async def _setup(hass: HomeAssistant) -> APSensor:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    reg = dr.async_get(hass)
    # Parent cluster + the AP device so via_device_id and the id both resolve.
    reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_cluster")},
        name="Cluster",
    )
    reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_{_mac_slug(_AP_MAC)}")},
        name="AP",
    )
    entity = APSensor(_coord(), entry.entry_id, _AP_MAC, AP_SENSOR_DESCRIPTIONS[0])
    entity.hass = hass
    return entity


async def test_removal_tears_down_subscription_and_resubscribes(
    hass: HomeAssistant,
) -> None:
    entity = await _setup(hass)
    entity._reconcile_device_info()
    assert entity._device_id is not None
    assert entity._unsub_devreg is not None  # subscription established

    # Device removed: id cleared and the dead subscription torn down.
    entity._on_devreg_updated(SimpleNamespace(data={"action": "remove"}))  # type: ignore[arg-type]
    assert entity._device_id is None
    assert entity._unsub_devreg is None

    # A device with the same identifier is present again — the next reconcile
    # must re-resolve the id and establish a *fresh* subscription.
    entity._reconcile_device_info()
    assert entity._device_id is not None
    assert entity._unsub_devreg is not None
    entity._stop_devinfo_reconcile()


async def test_transient_via_miss_preserves_existing_link(
    hass: HomeAssistant,
) -> None:
    """A parent (cluster) that can't be resolved this tick must NOT clear a good
    link.

    Regression: an unresolved via_identifier wrote via_device_id=None, wiping an
    already-established parent link instead of leaving it and retrying.
    """
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    reg = dr.async_get(hass)
    parent = reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "existing_parent")},
        name="Parent",
    )
    ap_id = (DOMAIN, f"{entry.entry_id}_{_mac_slug(_AP_MAC)}")
    ap = reg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={ap_id}, name="AP"
    )
    reg.async_update_device(ap.id, via_device_id=parent.id)
    # The AP's real via target (the cluster device) is deliberately NOT created,
    # so this tick's via_identifier resolution misses.
    entity = APSensor(_coord(), entry.entry_id, _AP_MAC, AP_SENSOR_DESCRIPTIONS[0])
    entity.hass = hass
    entity._reconcile_device_info()

    got = reg.async_get_device_by_identifier(ap_id, entry.entry_id)
    assert got is not None
    assert got.via_device_id == parent.id  # existing link preserved, not cleared
    assert entity._applied_key is None  # via unresolved → will retry next tick
    entity._stop_devinfo_reconcile()
