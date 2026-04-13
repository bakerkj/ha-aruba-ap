# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for cluster-level sensor aggregation (ArubaClusterData totals)."""

import pytest

from collections.abc import Callable

from custom_components.aruba_instant_ap.sensor import (
    ArubaClusterData,
    ClusterSensorDescription,
    PerAPData,
    RadioData,
)


def _radio_type_fn(rt: str) -> Callable[[ArubaClusterData], int]:
    """Factory that binds *rt* so mypy can infer the single-arg signature."""
    return lambda data: data.clients_by_radio_type.get(rt, 0)


# =============================================================================
# Test fixtures / helpers
# =============================================================================


def _radio(clients: int, radio_type: str | None) -> RadioData:
    return RadioData(clients=clients, radio_type=radio_type)


def _ap(mac: str, radios: dict[int, RadioData]) -> PerAPData:
    return PerAPData(
        mac=mac, radios=radios, total_clients=sum(r.clients for r in radios.values())
    )


def _aggregate(aps: dict[str, PerAPData]) -> tuple[int, dict[str, int]]:
    """Mirror of the aggregation block in ArubaAPCoordinator._fetch_data."""
    total_clients = sum(ap.total_clients for ap in aps.values())
    clients_by_radio_type: dict[str, int] = {}
    for ap in aps.values():
        for radio in ap.radios.values():
            if radio.radio_type:
                clients_by_radio_type[radio.radio_type] = (
                    clients_by_radio_type.get(radio.radio_type, 0) + radio.clients
                )
    return total_clients, clients_by_radio_type


# =============================================================================
# ArubaClusterData defaults
# =============================================================================


def test_cluster_data_default_total_clients():
    assert ArubaClusterData().total_clients == 0


def test_cluster_data_default_clients_by_radio_type():
    assert ArubaClusterData().clients_by_radio_type == {}


def test_cluster_data_stores_values():
    data = ArubaClusterData(
        total_clients=15,
        clients_by_radio_type={"2.4 GHz": 5, "5 GHz": 10},
    )
    assert data.total_clients == 15
    assert data.clients_by_radio_type == {"2.4 GHz": 5, "5 GHz": 10}


# =============================================================================
# total_clients aggregation
# =============================================================================


def test_total_clients_no_aps():
    total, _ = _aggregate({})
    assert total == 0


def test_total_clients_single_ap_single_radio():
    aps = {"aa:bb:cc:dd:ee:ff": _ap("aa:bb:cc:dd:ee:ff", {0: _radio(5, "5 GHz")})}
    total, _ = _aggregate(aps)
    assert total == 5


def test_total_clients_single_ap_multiple_radios():
    aps = {
        "aa:bb:cc:dd:ee:ff": _ap(
            "aa:bb:cc:dd:ee:ff",
            {0: _radio(3, "2.4 GHz"), 1: _radio(7, "5 GHz")},
        )
    }
    total, _ = _aggregate(aps)
    assert total == 10


def test_total_clients_multiple_aps():
    aps = {
        "aa:bb:cc:dd:ee:01": _ap(
            "aa:bb:cc:dd:ee:01",
            {0: _radio(4, "2.4 GHz"), 1: _radio(6, "5 GHz")},
        ),
        "aa:bb:cc:dd:ee:02": _ap(
            "aa:bb:cc:dd:ee:02",
            {0: _radio(2, "2.4 GHz"), 1: _radio(8, "5 GHz")},
        ),
    }
    total, _ = _aggregate(aps)
    assert total == 20


def test_total_clients_zero():
    aps = {"aa:bb:cc:dd:ee:ff": _ap("aa:bb:cc:dd:ee:ff", {0: _radio(0, "5 GHz")})}
    total, _ = _aggregate(aps)
    assert total == 0


def test_total_clients_includes_radio_with_no_type():
    # Clients on a radio with no derived type still count toward total
    aps = {
        "aa:bb:cc:dd:ee:ff": _ap(
            "aa:bb:cc:dd:ee:ff",
            {0: _radio(5, None), 1: _radio(3, "5 GHz")},
        )
    }
    total, _ = _aggregate(aps)
    assert total == 8


# =============================================================================
# clients_by_radio_type aggregation
# =============================================================================


def test_by_type_single_radio_type():
    aps = {"aa:bb:cc:dd:ee:ff": _ap("aa:bb:cc:dd:ee:ff", {0: _radio(5, "5 GHz")})}
    _, by_type = _aggregate(aps)
    assert by_type == {"5 GHz": 5}


def test_by_type_mixed_radio_types_single_ap():
    aps = {
        "aa:bb:cc:dd:ee:ff": _ap(
            "aa:bb:cc:dd:ee:ff",
            {0: _radio(3, "2.4 GHz"), 1: _radio(7, "5 GHz")},
        )
    }
    _, by_type = _aggregate(aps)
    assert by_type == {"2.4 GHz": 3, "5 GHz": 7}


def test_by_type_sums_same_type_across_aps():
    aps = {
        "aa:bb:cc:dd:ee:01": _ap(
            "aa:bb:cc:dd:ee:01",
            {0: _radio(4, "2.4 GHz"), 1: _radio(6, "5 GHz")},
        ),
        "aa:bb:cc:dd:ee:02": _ap(
            "aa:bb:cc:dd:ee:02",
            {0: _radio(2, "2.4 GHz"), 1: _radio(8, "5 GHz")},
        ),
    }
    _, by_type = _aggregate(aps)
    assert by_type == {"2.4 GHz": 6, "5 GHz": 14}


def test_by_type_ignores_none_radio_type():
    aps = {
        "aa:bb:cc:dd:ee:ff": _ap(
            "aa:bb:cc:dd:ee:ff",
            {0: _radio(5, None), 1: _radio(3, "5 GHz")},
        )
    }
    _, by_type = _aggregate(aps)
    assert "5 GHz" in by_type
    assert None not in by_type
    assert by_type["5 GHz"] == 3


def test_by_type_zero_client_radio_included():
    # A radio with 0 clients still appears if radio_type is known
    aps = {
        "aa:bb:cc:dd:ee:ff": _ap(
            "aa:bb:cc:dd:ee:ff",
            {0: _radio(0, "2.4 GHz"), 1: _radio(5, "5 GHz")},
        )
    }
    _, by_type = _aggregate(aps)
    assert by_type["2.4 GHz"] == 0
    assert by_type["5 GHz"] == 5


def test_by_type_no_aps_returns_empty():
    _, by_type = _aggregate({})
    assert by_type == {}


def test_by_type_all_radios_no_type():
    aps = {
        "aa:bb:cc:dd:ee:ff": _ap(
            "aa:bb:cc:dd:ee:ff",
            {0: _radio(5, None), 1: _radio(3, None)},
        )
    }
    _, by_type = _aggregate(aps)
    assert by_type == {}


# =============================================================================
# ClusterSensorDescription value_fn
# =============================================================================


def test_description_total_clients_value_fn():
    data = ArubaClusterData(total_clients=42)
    desc = ClusterSensorDescription(
        key="total_clients",
        name="Total Clients",
        value_fn=lambda d: d.total_clients,
    )
    assert desc.value_fn(data) == 42


def test_description_total_clients_zero():
    data = ArubaClusterData(total_clients=0)
    desc = ClusterSensorDescription(
        key="total_clients",
        name="Total Clients",
        value_fn=lambda d: d.total_clients,
    )
    assert desc.value_fn(data) == 0


@pytest.mark.parametrize(
    "radio_type,expected",
    [
        ("2.4 GHz", 4),
        ("5 GHz", 10),
    ],
)
def test_description_radio_type_value_fn(radio_type: str, expected: int):
    data = ArubaClusterData(clients_by_radio_type={"2.4 GHz": 4, "5 GHz": 10})
    desc = ClusterSensorDescription(
        key=f"clients_{radio_type}",
        name=f"{radio_type} Clients",
        value_fn=_radio_type_fn(radio_type),
    )
    assert desc.value_fn(data) == expected


def test_description_radio_type_missing_returns_zero():
    data = ArubaClusterData(clients_by_radio_type={"2.4 GHz": 4})
    desc = ClusterSensorDescription(
        key="clients_5_ghz",
        name="5 GHz Clients",
        value_fn=_radio_type_fn("5 GHz"),
    )
    assert desc.value_fn(data) == 0


def test_description_factory_captures_correct_radio_type():
    """Verify the _radio_type_fn factory used in async_setup_entry isolates each type."""
    data = ArubaClusterData(clients_by_radio_type={"2.4 GHz": 3, "5 GHz": 9})
    descriptions = [
        ClusterSensorDescription(
            key=f"clients_{radio_type}",
            name=f"{radio_type} Clients",
            value_fn=_radio_type_fn(radio_type),
        )
        for radio_type in ("2.4 GHz", "5 GHz")
    ]
    assert descriptions[0].value_fn(data) == 3
    assert descriptions[1].value_fn(data) == 9
