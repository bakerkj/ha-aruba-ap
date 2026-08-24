# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""The AP device publishes its own ethernet MAC as a linkable connection.

This lets another integration that learns the same MAC -- e.g. a switch-port
integration seeing this AP as its LLDP neighbor on the uplink port -- link the
physical switch port to this AP device. The standard ``mac`` type is gated by
SPLIT_REGISTRY, exactly like the client path.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from homeassistant.helpers import device_registry as dr

from custom_components.aruba_instant_ap.const import SPLIT_REGISTRY
from custom_components.aruba_instant_ap.sensor import (
    AP_SENSOR_DESCRIPTIONS,
    APSensor,
    _ap_network_connections,
)

_AP_MAC = "d0:d3:e0:c6:53:46"


def test_ap_network_connection_is_gated_by_split_registry() -> None:
    conns = _ap_network_connections(_AP_MAC)
    published = (dr.CONNECTION_NETWORK_MAC, _AP_MAC) in conns
    assert published is SPLIT_REGISTRY


def test_ap_device_info_carries_the_mac_connection() -> None:
    coord: Any = MagicMock()
    coord.data.aps = {
        _AP_MAC: SimpleNamespace(
            name="1st Living", model="515", firmware="8.13", serial="XYZ"
        )
    }
    entity = APSensor(coord, "entry", _AP_MAC, AP_SENSOR_DESCRIPTIONS[0])

    device_info = entity.device_info
    assert device_info is not None
    connections = device_info.get("connections", set())
    published = (dr.CONNECTION_NETWORK_MAC, _AP_MAC) in connections
    assert published is SPLIT_REGISTRY
