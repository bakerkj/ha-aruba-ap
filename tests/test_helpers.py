# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for pure helper functions in sensor.py."""

import pytest

from custom_components.aruba_instant_ap.sensor import (
    _as_int,
    _client_display_name,
    _counter_rate,
    _derive_connection_type,
    _derive_radio_type,
    _find_radio_for_bssid,
    _first_value,
    _hex_to_mac,
    _mac_slug,
    _parse_mac_table,
    _parse_radio_table,
    _safe_walk,
    _ticks_to_seconds,
)
from custom_components.aruba_instant_ap.const import (
    OID_AP_NAME,
    OID_CLIENT_HOSTNAME,
    OID_RADIO_CHANNEL,
)

# ── _as_int ───────────────────────────────────────────────────────────────────


def test_as_int_valid():
    assert _as_int("42") == 42


def test_as_int_zero():
    assert _as_int("0") == 0


def test_as_int_none():
    assert _as_int(None) is None


def test_as_int_non_numeric():
    assert _as_int("abc") is None


def test_as_int_empty():
    assert _as_int("") is None


# ── _mac_slug ─────────────────────────────────────────────────────────────────


def test_mac_slug_strips_colons():
    assert _mac_slug("aa:bb:cc:dd:ee:ff") == "aabbccddeeff"


def test_mac_slug_already_clean():
    assert _mac_slug("aabbccddeeff") == "aabbccddeeff"


# ── _first_value ──────────────────────────────────────────────────────────────


def test_first_value_returns_first():
    assert _first_value({"a": "1", "b": "2"}) == "1"


def test_first_value_empty():
    assert _first_value({}) is None


def test_first_value_none():
    assert _first_value(None) is None


# ── _hex_to_mac ───────────────────────────────────────────────────────────────


def test_hex_to_mac_0x_prefix():
    assert _hex_to_mac("0x1c28afb46242") == "1c:28:af:b4:62:42"


def test_hex_to_mac_space_separated():
    assert _hex_to_mac("1c 28 af b4 62 42") == "1c:28:af:b4:62:42"


def test_hex_to_mac_colon_separated():
    assert _hex_to_mac("1c:28:af:b4:62:42") == "1c:28:af:b4:62:42"


def test_hex_to_mac_uppercase_normalised():
    assert _hex_to_mac("1C:28:AF:B4:62:42") == "1c:28:af:b4:62:42"


def test_hex_to_mac_too_short():
    assert _hex_to_mac("0x1234") is None


def test_hex_to_mac_none():
    assert _hex_to_mac(None) is None


def test_hex_to_mac_empty():
    assert _hex_to_mac("") is None


# ── _ticks_to_seconds ─────────────────────────────────────────────────────────


def test_ticks_to_seconds_basic():
    assert _ticks_to_seconds("36000") == 360


def test_ticks_to_seconds_truncates():
    # 101 centiseconds → 1 second (integer division)
    assert _ticks_to_seconds("101") == 1


def test_ticks_to_seconds_none():
    assert _ticks_to_seconds(None) is None


def test_ticks_to_seconds_non_numeric():
    assert _ticks_to_seconds("abc") is None


# ── _safe_walk ────────────────────────────────────────────────────────────────


def test_safe_walk_passthrough():
    d = {"1.2.3": "val"}
    assert _safe_walk(d) == d


def test_safe_walk_exception_returns_empty():
    assert _safe_walk(RuntimeError("oops")) == {}


def test_safe_walk_non_dict_returns_empty():
    assert _safe_walk("not-a-dict") == {}


# ── _counter_rate ─────────────────────────────────────────────────────────────


def test_counter_rate_basic():
    assert _counter_rate(200, 100, 10.0) == 10.0


def test_counter_rate_wrap_around():
    # 32-bit counter wraps: current < previous
    assert _counter_rate(10, 2**32 - 90, 10.0) == 10.0


def test_counter_rate_zero_dt():
    assert _counter_rate(200, 100, 0.0) is None


def test_counter_rate_no_change():
    assert _counter_rate(100, 100, 10.0) == 0.0


# ── _derive_radio_type ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "channel,expected",
    [
        ("6", "2.4 GHz"),
        ("1", "2.4 GHz"),
        ("11", "2.4 GHz"),
        ("36", "5 GHz"),
        ("100S", "5 GHz"),
        ("36+", "5 GHz"),
        ("149-", "5 GHz"),
        (None, None),
        ("", None),
        ("6E", "2.4 GHz"),  # 'E' strips, leaving '6' which is in 1-14 → 2.4 GHz
    ],
)
def test_derive_radio_type(channel, expected):
    assert _derive_radio_type(channel) == expected


# ── _parse_mac_table ──────────────────────────────────────────────────────────

# AP table: MAC is the first 6 octets of the OID suffix
_AP_MAC = "aa:bb:cc:dd:ee:ff"
_AP_MAC_INTS = "170.187.204.221.238.255"  # decimal


def _ap_oid(base: str, suffix: str = "") -> str:
    return f"{base}.{_AP_MAC_INTS}" + (f".{suffix}" if suffix else "")


def test_parse_mac_table_head():
    raw = {_ap_oid(OID_AP_NAME): "MyAP"}
    result = _parse_mac_table(raw, OID_AP_NAME, tail=False)
    assert result == {_AP_MAC: "MyAP"}


def test_parse_mac_table_tail():
    # Client table: MAC is the *last* 6 octets; OID suffix is extra.0.MAC
    base = OID_CLIENT_HOSTNAME
    raw = {f"{base}.0.{_AP_MAC_INTS}": "my-laptop"}
    result = _parse_mac_table(raw, base, tail=True)
    assert result == {_AP_MAC: "my-laptop"}


def test_parse_mac_table_ignores_short_suffix():
    raw = {f"{OID_AP_NAME}.1.2.3": "bad"}
    result = _parse_mac_table(raw, OID_AP_NAME)
    assert result == {}


def test_parse_mac_table_ignores_wrong_prefix():
    raw = {"1.2.3.4.5.6.7.8.9.10.11": "val"}
    result = _parse_mac_table(raw, OID_AP_NAME)
    assert result == {}


# ── _parse_radio_table ────────────────────────────────────────────────────────


def test_parse_radio_table_basic():
    # Radio table suffix: mac_b0…mac_b5.radio_idx
    raw = {f"{OID_RADIO_CHANNEL}.{_AP_MAC_INTS}.0": "36"}
    result = _parse_radio_table(raw, OID_RADIO_CHANNEL)
    assert result == {(_AP_MAC, 0): "36"}


def test_parse_radio_table_multiple_radios():
    raw = {
        f"{OID_RADIO_CHANNEL}.{_AP_MAC_INTS}.0": "36",
        f"{OID_RADIO_CHANNEL}.{_AP_MAC_INTS}.1": "6",
    }
    result = _parse_radio_table(raw, OID_RADIO_CHANNEL)
    assert result[(_AP_MAC, 0)] == "36"
    assert result[(_AP_MAC, 1)] == "6"


def test_parse_radio_table_ignores_short_suffix():
    raw = {f"{OID_RADIO_CHANNEL}.1.2.3.4": "val"}
    result = _parse_radio_table(raw, OID_RADIO_CHANNEL)
    assert result == {}


# ── _find_radio_for_bssid ─────────────────────────────────────────────────────


def test_find_radio_for_bssid_exact_match():
    # Base BSSID ends in :10; client BSSID ends in :12 (same upper nibble 0x10)
    radio_base_bssids = {("aa:bb:cc:dd:ee:ff", 0): "11:22:33:44:55:10"}
    result = _find_radio_for_bssid("11:22:33:44:55:12", radio_base_bssids)
    assert result == ("aa:bb:cc:dd:ee:ff", 0)


def test_find_radio_for_bssid_different_nibble():
    # Base BSSID ends in :10 (nibble 0x10); client ends in :20 (nibble 0x20) → no match
    radio_base_bssids = {("aa:bb:cc:dd:ee:ff", 0): "11:22:33:44:55:10"}
    result = _find_radio_for_bssid("11:22:33:44:55:20", radio_base_bssids)
    assert result is None


def test_find_radio_for_bssid_wrong_prefix():
    radio_base_bssids = {("aa:bb:cc:dd:ee:ff", 0): "11:22:33:44:55:10"}
    result = _find_radio_for_bssid("ff:ff:ff:ff:ff:10", radio_base_bssids)
    assert result is None


def test_find_radio_for_bssid_malformed():
    assert _find_radio_for_bssid("not-a-mac", {}) is None


def test_find_radio_for_bssid_selects_correct_radio():
    # Two radios on same AP; client belongs to radio 1
    radio_base_bssids = {
        ("aa:bb:cc:dd:ee:ff", 0): "11:22:33:44:55:10",
        ("aa:bb:cc:dd:ee:ff", 1): "11:22:33:44:55:20",
    }
    result = _find_radio_for_bssid("11:22:33:44:55:23", radio_base_bssids)
    assert result == ("aa:bb:cc:dd:ee:ff", 1)


# ── _derive_connection_type ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "phy_type,ht_mode,expected",
    [
        (5, None, "wired"),
        (6, None, "802.11ax (Wi-Fi 6E)"),
        (1, 6, "802.11ac"),  # 5 GHz VHT80
        (1, 9, "802.11ax (Wi-Fi 6)"),  # 5 GHz HE20
        (3, 9, "802.11ax"),  # 2.4 GHz HE
        (1, 3, "802.11an"),  # 5 GHz HT40
        (3, 3, "802.11gn"),  # 2.4 GHz HT40
        (1, 1, "802.11a"),  # legacy 5 GHz
        (2, 1, "802.11b"),  # legacy 2.4 GHz
        (None, 6, None),  # no phy type
    ],
)
def test_derive_connection_type(phy_type, ht_mode, expected):
    assert _derive_connection_type(phy_type, ht_mode) == expected


# ── _client_display_name ──────────────────────────────────────────────────────


def test_client_display_name_with_name():
    client = {"name": "Alice's iPhone"}
    assert (
        _client_display_name(client, "aa:bb:cc:dd:ee:ff")
        == "Alice's iPhone / aa:bb:cc:dd:ee:ff"
    )


def test_client_display_name_no_name():
    assert _client_display_name({}, "aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"


def test_client_display_name_none_client():
    assert _client_display_name(None, "aa:bb:cc:dd:ee:ff") == "aa:bb:cc:dd:ee:ff"
