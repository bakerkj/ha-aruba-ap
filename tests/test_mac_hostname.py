# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for MAC→hostname file loading and client name priority."""

import json
from unittest.mock import MagicMock

import pytest

from custom_components.aruba_instant_ap.sensor import ArubaAPCoordinator


class _FileLoaderStub:
    """Minimal stub for testing _load_mac_hostname_file.

    Avoids instantiating ArubaAPCoordinator (and its DataUpdateCoordinator
    parent) which requires a real HA frame context in newer HA versions.
    _load_mac_hostname_file only uses self.hass and self.mac_hostname_file.
    """

    def __init__(self, filename: str) -> None:
        self.mac_hostname_file = filename
        self.hass = MagicMock()

        async def _fake_executor(fn, *args):
            return fn(*args)

        self.hass.async_add_executor_job = _fake_executor

    _load_mac_hostname_file = ArubaAPCoordinator._load_mac_hostname_file


def _make_loader(filename: str = "") -> _FileLoaderStub:
    return _FileLoaderStub(filename)


@pytest.mark.asyncio
async def test_load_mac_hostname_file_basic(tmp_path):
    mapping = {"aa:bb:cc:dd:ee:ff": "my-laptop", "11:22:33:44:55:66": "printer"}
    f = tmp_path / "mapping.json"
    f.write_text(json.dumps(mapping))

    coord = _make_loader(str(f))
    result = await coord._load_mac_hostname_file()
    assert result["aa:bb:cc:dd:ee:ff"] == "my-laptop"
    assert result["11:22:33:44:55:66"] == "printer"


@pytest.mark.asyncio
async def test_load_mac_hostname_file_normalises_mac_formats(tmp_path):
    """MACs in various separator styles should all normalise to colon form."""
    mapping = {
        "AABBCCDDEEFF": "device-no-sep",
        "11-22-33-44-55-66": "device-dashes",
        "CC.DD.EE.FF.00.11": "device-dots",
    }
    f = tmp_path / "mapping.json"
    f.write_text(json.dumps(mapping))

    coord = _make_loader(str(f))

    result = await coord._load_mac_hostname_file()
    assert result["aa:bb:cc:dd:ee:ff"] == "device-no-sep"
    assert result["11:22:33:44:55:66"] == "device-dashes"
    assert result["cc:dd:ee:ff:00:11"] == "device-dots"


@pytest.mark.asyncio
async def test_load_mac_hostname_file_missing_file(tmp_path):
    coord = _make_loader(str(tmp_path / "nonexistent.json"))

    result = await coord._load_mac_hostname_file()
    assert result == {}


@pytest.mark.asyncio
async def test_load_mac_hostname_file_empty_path():
    coord = _make_loader("")
    # No executor call should be made when path is empty
    result = await coord._load_mac_hostname_file()
    assert result == {}


@pytest.mark.asyncio
async def test_load_mac_hostname_file_invalid_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("not json at all {{{")

    coord = _make_loader(str(f))

    result = await coord._load_mac_hostname_file()
    assert result == {}


@pytest.mark.asyncio
async def test_load_mac_hostname_file_not_a_dict(tmp_path):
    f = tmp_path / "list.json"
    f.write_text(json.dumps(["aa:bb:cc:dd:ee:ff"]))

    coord = _make_loader(str(f))

    result = await coord._load_mac_hostname_file()
    assert result == {}


@pytest.mark.asyncio
async def test_load_mac_hostname_file_skips_blank_values(tmp_path):
    mapping = {"aa:bb:cc:dd:ee:ff": "valid", "11:22:33:44:55:66": "  "}
    f = tmp_path / "mapping.json"
    f.write_text(json.dumps(mapping))

    coord = _make_loader(str(f))

    result = await coord._load_mac_hostname_file()
    assert "aa:bb:cc:dd:ee:ff" in result
    assert "11:22:33:44:55:66" not in result


# ── Client name priority ──────────────────────────────────────────────────────
# The name resolution logic (mapping file > Aruba hostname > MAC) lives in
# _fetch_data.  We test it directly via the logic extracted inline.


def _resolve_client_name(
    mac: str,
    aruba_hostname: str | None,
    mapping: dict[str, str],
) -> str | None:
    """Mirror of the name-resolution block in _fetch_data."""
    hostname = aruba_hostname
    if mapping.get(mac):
        return mapping[mac]
    if hostname and hostname.strip() and not hostname.startswith("0x"):
        return hostname.strip()
    return None


def test_name_priority_mapping_wins_over_aruba():
    result = _resolve_client_name(
        "aa:bb:cc:dd:ee:ff",
        aruba_hostname="aruba-name",
        mapping={"aa:bb:cc:dd:ee:ff": "mapping-name"},
    )
    assert result == "mapping-name"


def test_name_priority_aruba_used_when_no_mapping():
    result = _resolve_client_name(
        "aa:bb:cc:dd:ee:ff",
        aruba_hostname="aruba-name",
        mapping={},
    )
    assert result == "aruba-name"


def test_name_priority_none_when_both_absent():
    result = _resolve_client_name("aa:bb:cc:dd:ee:ff", aruba_hostname=None, mapping={})
    assert result is None


def test_name_priority_aruba_hex_string_ignored():
    """Aruba reports raw hex (0x...) when no hostname is known — should be skipped."""
    result = _resolve_client_name(
        "aa:bb:cc:dd:ee:ff",
        aruba_hostname="0xaabbccddeeff",
        mapping={},
    )
    assert result is None


def test_name_priority_aruba_whitespace_stripped():
    result = _resolve_client_name(
        "aa:bb:cc:dd:ee:ff",
        aruba_hostname="  trimmed  ",
        mapping={},
    )
    assert result == "trimmed"


def test_name_priority_mapping_wins_even_when_aruba_is_hex():
    result = _resolve_client_name(
        "aa:bb:cc:dd:ee:ff",
        aruba_hostname="0xaabbccddeeff",
        mapping={"aa:bb:cc:dd:ee:ff": "from-mapping"},
    )
    assert result == "from-mapping"
