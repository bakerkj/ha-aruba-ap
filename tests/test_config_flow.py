# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Tests for config_flow — initial setup and reconfigure steps."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aruba_instant_ap.const import (
    CONF_CLIENTS_MAPPED_ONLY,
    CONF_COMMUNITY,
    CONF_HOST,
    CONF_MAC_HOSTNAME_FILE,
    CONF_SNMP_PORT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_SNMP_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_DEFAULT_DATA = {
    CONF_HOST: "192.168.1.1",
    CONF_COMMUNITY: "public",
    CONF_SNMP_PORT: DEFAULT_SNMP_PORT,
}

_DEFAULT_OPTIONS = {
    "snmp_version": "v2c",
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
    CONF_MAC_HOSTNAME_FILE: "",
    CONF_CLIENTS_MAPPED_ONLY: False,
}

_RECONFIGURE_INPUT = {
    CONF_HOST: "192.168.1.1",
    CONF_COMMUNITY: "public",
    CONF_SNMP_PORT: DEFAULT_SNMP_PORT,
    "snmp_version": "v2c",
    CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
    CONF_MAC_HOSTNAME_FILE: "",
}


def _make_entry(options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data=_DEFAULT_DATA,
        options=options or _DEFAULT_OPTIONS,
        entry_id="test_entry",
    )


# ── reconfigure — clients_mapped_only regression ──────────────────────────────


async def test_reconfigure_clients_mapped_only_true_succeeds(hass):
    """Enabling clients_mapped_only via reconfigure must not raise TypeError.

    Regression: async_update_reload_and_abort was called with options_updates=
    which is not accepted in all HA releases. The fix uses options= instead.
    The flow must complete with abort reason 'reconfigure_successful' and the
    option must be persisted on the entry.
    """
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.aruba_instant_ap.config_flow._test_connection",
            new=AsyncMock(return_value=None),
        ),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": entry.entry_id},
        )
        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={**_RECONFIGURE_INPUT, CONF_CLIENTS_MAPPED_ONLY: True},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.options[CONF_CLIENTS_MAPPED_ONLY] is True


async def test_reconfigure_clients_mapped_only_false_succeeds(hass):
    """Disabling clients_mapped_only via reconfigure also completes cleanly."""
    entry = _make_entry(options={**_DEFAULT_OPTIONS, CONF_CLIENTS_MAPPED_ONLY: True})
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.aruba_instant_ap.config_flow._test_connection",
            new=AsyncMock(return_value=None),
        ),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={**_RECONFIGURE_INPUT, CONF_CLIENTS_MAPPED_ONLY: False},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.options[CONF_CLIENTS_MAPPED_ONLY] is False


async def test_reconfigure_all_options_persisted(hass):
    """All options submitted during reconfigure are saved to entry.options."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.aruba_instant_ap.config_flow._test_connection",
            new=AsyncMock(return_value=None),
        ),
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_HOST: "10.0.0.1",
                CONF_COMMUNITY: "private",
                CONF_SNMP_PORT: 1161,
                "snmp_version": "v1",
                CONF_UPDATE_INTERVAL: 30,
                CONF_MAC_HOSTNAME_FILE: "/tmp/map.json",
                CONF_CLIENTS_MAPPED_ONLY: True,
            },
        )

    assert result["type"] == "abort"
    assert entry.options["snmp_version"] == "v1"
    assert entry.options[CONF_UPDATE_INTERVAL] == 30
    assert entry.options[CONF_MAC_HOSTNAME_FILE] == "/tmp/map.json"
    assert entry.options[CONF_CLIENTS_MAPPED_ONLY] is True


async def test_reconfigure_connection_failure_shows_error(hass):
    """A failed SNMP test during reconfigure shows 'cannot_connect', not 'unknown'."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.aruba_instant_ap.config_flow._test_connection",
        new=AsyncMock(side_effect=ConnectionError("unreachable")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reconfigure", "entry_id": entry.entry_id},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={**_RECONFIGURE_INPUT, CONF_CLIENTS_MAPPED_ONLY: True},
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"
