# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for sensor description enabled_default values.

Verifies that each sensor description has the correct enabled_default so that
the entity registry disables noisy/diagnostic sensors by default while keeping
core sensors enabled.

Also verifies that each entity class correctly propagates enabled_default from
its description to _attr_entity_registry_enabled_default.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.aruba_instant_ap.sensor import (
    AP_SENSOR_DESCRIPTIONS,
    APSensor,
    APSensorDescription,
    CLIENT_SENSOR_DESCRIPTIONS,
    ClientSensor,
    ClientSensorDescription,
    RADIO_SENSOR_DESCRIPTIONS,
    RadioSensor,
    RadioSensorDescription,
)

# ── AP descriptions ───────────────────────────────────────────────────────────

AP_ENABLED = {
    "total_clients",
    "firmware",
    "boot_time",
    "cpu_usage",
    "memory_usage",
}

AP_DISABLED = {
    "ap_status",
    # superseded by the stable "boot_time" timestamp; the seconds counter
    # writes a recorder row every poll, so it's off by default
    "uptime",
}


@pytest.mark.parametrize(
    "desc",
    [d for d in AP_SENSOR_DESCRIPTIONS if d.key in AP_ENABLED],
    ids=lambda d: d.key,
)
def test_ap_sensor_enabled_by_default(desc):
    assert desc.enabled_default is True, (
        f"AP sensor '{desc.key}' should be enabled by default"
    )


@pytest.mark.parametrize(
    "desc",
    [d for d in AP_SENSOR_DESCRIPTIONS if d.key in AP_DISABLED],
    ids=lambda d: d.key,
)
def test_ap_sensor_disabled_by_default(desc):
    assert desc.enabled_default is False, (
        f"AP sensor '{desc.key}' should be disabled by default"
    )


def test_ap_descriptions_cover_all_keys():
    """Guard against new sensors being added without a deliberate enabled_default."""
    all_keys = {d.key for d in AP_SENSOR_DESCRIPTIONS}
    assert all_keys == AP_ENABLED | AP_DISABLED, (
        f"Unclassified AP sensors: {all_keys - AP_ENABLED - AP_DISABLED}"
    )


# ── Radio descriptions ────────────────────────────────────────────────────────

RADIO_ENABLED = {
    "channel",
    "tx_power",
    "clients",
    "utilization",
    "radio_type",
    "tx_rate",
    "rx_rate",
    "noise_floor",
}

RADIO_DISABLED = {
    "status",
    "tx_total_frame_rate",
    "tx_mgmt_frame_rate",
    "tx_data_frame_rate",
    "rx_total_frame_rate",
    "rx_data_frame_rate",
    "rx_mgmt_frame_rate",
    "tx_dropped_rate",
    "rx_bad_rate",
    "phy_event_rate",
    "utilization_64",
}


@pytest.mark.parametrize(
    "desc",
    [d for d in RADIO_SENSOR_DESCRIPTIONS if d.key in RADIO_ENABLED],
    ids=lambda d: d.key,
)
def test_radio_sensor_enabled_by_default(desc):
    assert desc.enabled_default is True, (
        f"Radio sensor '{desc.key}' should be enabled by default"
    )


@pytest.mark.parametrize(
    "desc",
    [d for d in RADIO_SENSOR_DESCRIPTIONS if d.key in RADIO_DISABLED],
    ids=lambda d: d.key,
)
def test_radio_sensor_disabled_by_default(desc):
    assert desc.enabled_default is False, (
        f"Radio sensor '{desc.key}' should be disabled by default"
    )


def test_radio_descriptions_cover_all_keys():
    """Guard against new sensors being added without a deliberate enabled_default."""
    all_keys = {d.key for d in RADIO_SENSOR_DESCRIPTIONS}
    assert all_keys == RADIO_ENABLED | RADIO_DISABLED, (
        f"Unclassified radio sensors: {all_keys - RADIO_ENABLED - RADIO_DISABLED}"
    )


# ── Client descriptions ───────────────────────────────────────────────────────

CLIENT_ENABLED = {
    "snr",
    "tx_rate",
    "rx_rate",
    "connection_type",
    "speed",
    "ip",
    "ssid",
    "ap_name",
}

CLIENT_DISABLED = {
    "ht_mode",
    "connection_uptime",
    "channel",
    "mac",
    "name",
    "os_type",
    "rx_speed",
    "tx_retry_rate",
    "rx_retry_rate",
}


@pytest.mark.parametrize(
    "desc",
    [d for d in CLIENT_SENSOR_DESCRIPTIONS if d.key in CLIENT_ENABLED],
    ids=lambda d: d.key,
)
def test_client_sensor_enabled_by_default(desc):
    assert desc.enabled_default is True, (
        f"Client sensor '{desc.key}' should be enabled by default"
    )


@pytest.mark.parametrize(
    "desc",
    [d for d in CLIENT_SENSOR_DESCRIPTIONS if d.key in CLIENT_DISABLED],
    ids=lambda d: d.key,
)
def test_client_sensor_disabled_by_default(desc):
    assert desc.enabled_default is False, (
        f"Client sensor '{desc.key}' should be disabled by default"
    )


def test_client_descriptions_cover_all_keys():
    """Guard against new sensors being added without a deliberate enabled_default."""
    all_keys = {d.key for d in CLIENT_SENSOR_DESCRIPTIONS}
    assert all_keys == CLIENT_ENABLED | CLIENT_DISABLED, (
        f"Unclassified client sensors: {all_keys - CLIENT_ENABLED - CLIENT_DISABLED}"
    )


# ── Entity wiring: enabled_default → _attr_entity_registry_enabled_default ───
#
# Each entity class must propagate description.enabled_default to
# _attr_entity_registry_enabled_default in __init__.  These tests instantiate
# the entity with a minimal mock coordinator to verify the wiring without
# needing a full HA environment.


def _make_coordinator(ap_mac: str = "aa:bb:cc:dd:ee:ff") -> MagicMock:
    """Return a minimal coordinator mock sufficient to construct any entity."""
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


@pytest.mark.parametrize("enabled", [True, False])
def test_ap_sensor_entity_wires_enabled_default(enabled):
    desc = APSensorDescription(
        key="test_key",
        name="Test",
        value_fn=lambda ap: None,
        enabled_default=enabled,
    )
    entity = APSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", desc)
    assert entity._attr_entity_registry_enabled_default is enabled


@pytest.mark.parametrize("enabled", [True, False])
def test_radio_sensor_entity_wires_enabled_default(enabled):
    desc = RadioSensorDescription(
        key="test_key",
        name="Test",
        value_fn=lambda r: None,
        enabled_default=enabled,
    )
    entity = RadioSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", 0, desc)
    assert entity._attr_entity_registry_enabled_default is enabled


@pytest.mark.parametrize("enabled", [True, False])
def test_client_sensor_entity_wires_enabled_default(enabled):
    desc = ClientSensorDescription(
        key="test_key",
        name="Test",
        value_fn=lambda c: None,
        enabled_default=enabled,
    )
    entity = ClientSensor(_make_coordinator(), "entry1", "aa:bb:cc:dd:ee:ff", desc)
    assert entity._attr_entity_registry_enabled_default is enabled
