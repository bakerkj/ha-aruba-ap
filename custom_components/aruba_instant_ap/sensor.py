# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Sensor platform for Aruba Instant AP."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfDataRate, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry
from homeassistant.util import dt as dt_util, slugify
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CLIENT_PHY_TYPE_MAP,
    DOMAIN,
    OID_AP_CPU_USAGE,
    OID_AP_IP,
    OID_AP_MEM_FREE,
    OID_AP_MEM_TOTAL,
    OID_AP_MODEL,
    OID_AP_NAME,
    OID_AP_ROLE,
    OID_AP_SERIAL,
    OID_AP_STATUS,
    OID_AP_SW_VERSION,
    OID_AP_UPTIME,
    OID_BSS_BSSID,
    OID_BSS_SSID,
    OID_CLIENT_BSSID,
    OID_CLIENT_HOSTNAME,
    OID_CLIENT_IP,
    OID_CLIENT_HT_MODE,
    OID_CLIENT_OS,
    OID_CLIENT_PHY_TYPE,
    OID_CLIENT_RX_BYTES,
    OID_CLIENT_RX_RATE,
    OID_CLIENT_RX_RETRIES,
    OID_CLIENT_SNR,
    OID_CLIENT_SPEED,
    OID_CLIENT_TX_BYTES,
    OID_CLIENT_TX_RETRIES,
    OID_CLIENT_UPTIME,
    OID_RADIO_BSSID,
    OID_RADIO_CHANNEL,
    OID_RADIO_CLIENTS,
    OID_RADIO_NOISE_FLOOR,
    OID_RADIO_PHY_EVENTS,
    OID_RADIO_RX_BAD,
    OID_RADIO_RX_BYTES,
    OID_RADIO_RX_DATA_FRAMES,
    OID_RADIO_RX_MGMT,
    OID_RADIO_RX_TOTAL_FRAMES,
    OID_RADIO_STATUS,
    OID_RADIO_TX_BYTES,
    OID_RADIO_TX_DATA_FRAMES,
    OID_RADIO_TX_DROPPED,
    OID_RADIO_TX_MGMT,
    OID_RADIO_TX_TOTAL_FRAMES,
    OID_RADIO_TX_POWER,
    OID_RADIO_UTILIZATION,
    OID_RADIO_UTILIZATION64,
)
from .snmp_helper import async_snmp_walk

_LOGGER = logging.getLogger(__name__)

# Max drift (seconds) between successive computed AP boot times before we treat
# it as a real change (reboot / clock correction) rather than poll jitter. The
# raw `now - uptime` value wobbles a few seconds every poll from scheduling and
# the SNMP TimeTicks // 100 truncation; without this the timestamp would change
# every poll and save nothing.
_BOOT_TIME_TOLERANCE_S = 30

# 32-bit counter wrap-around value
_MAX32: int = 2**32


def _as_int(v: str | None) -> int | None:
    """Parse a string value to int, returning None on failure."""
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _mac_slug(mac: str) -> str:
    """Strip colons from a MAC address for use in identifiers."""
    return mac.replace(":", "")


# aiClientHtMode integer → channel width in MHz (None for legacy/unknown)
_HT_MODE_MHZ: dict[int, int | None] = {
    1: 20,  # legacy (802.11a/b/g) — always 20 MHz
    2: 20,  # HT20
    3: 40,  # HT40
    4: 20,  # VHT20
    5: 40,  # VHT40
    6: 80,  # VHT80
    7: 160,  # VHT160
    8: 160,  # VHT80+80 (160 MHz total)
    9: 20,  # HE20
    10: 40,  # HE40
    11: 80,  # HE80
    12: 160,  # HE160
    13: 160,  # HE80+80 (160 MHz total)
}


# =============================================================================
# Data structures
# =============================================================================


@dataclass
class RadioData:
    status: str = "off"  # "on" or "off"
    channel: str | None = None
    tx_power_dbm: int | None = None
    clients: int = 0
    utilization_pct: int | None = None
    utilization_64_pct: int | None = None
    radio_type: str | None = None
    noise_floor_dbm: int | None = None
    tx_bytes: int | None = None
    rx_bytes: int | None = None
    tx_total_frames: int | None = None  # aiRadioTxTotalFrames (col 9)
    tx_mgmt_frames: int | None = None  # aiRadioTxMgmtFrames (col 10)
    tx_data_frames: int | None = None  # aiRadioTxDataFrames (col 11)
    rx_total_frames: int | None = None  # aiRadioRxTotalFrames (col 14)
    rx_data_frames: int | None = None  # aiRadioRxDataFrames (col 15)
    rx_mgmt_frames: int | None = None  # aiRadioRxMgmtFrames (col 17)
    tx_dropped: int | None = None
    rx_bad_frames: int | None = None
    phy_events: int | None = None
    tx_bytes_per_sec: float | None = None
    rx_bytes_per_sec: float | None = None
    tx_total_per_sec: float | None = None
    tx_mgmt_per_sec: float | None = None
    tx_data_per_sec: float | None = None
    rx_total_per_sec: float | None = None
    rx_data_per_sec: float | None = None
    rx_mgmt_per_sec: float | None = None
    tx_dropped_per_sec: float | None = None
    rx_bad_per_sec: float | None = None
    phy_events_per_sec: float | None = None


@dataclass
class PerAPData:
    mac: str
    name: str | None = None
    ip: str | None = None
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None  # cluster-wide firmware
    status: str | None = None  # "up" or "down"
    uptime_seconds: int | None = None
    boot_time: datetime | None = None  # stable: only changes on reboot
    role: str | None = None  # "cluster conductor" / "cluster member"
    cpu_pct: int | None = None
    mem_free_bytes: int | None = None
    mem_total_bytes: int | None = None
    radios: dict[int, RadioData] = field(default_factory=dict)
    total_clients: int = 0


@dataclass
class ArubaClusterData:
    aps: dict[str, PerAPData] = field(default_factory=dict)  # mac → PerAPData
    clients: list[dict[str, Any]] = field(default_factory=list)
    firmware: str | None = None  # cluster firmware
    total_clients: int = 0
    clients_by_radio_type: dict[str, int] = field(default_factory=dict)


# =============================================================================
# Parse helpers
# =============================================================================


def _first_value(raw: dict[str, str]) -> str | None:
    """Return the first value from a walk (scalar OIDs)."""
    return next(iter(raw.values()), None) if raw else None


def _parse_mac_table(
    raw: dict[str, str], base_oid: str, *, tail: bool = False
) -> dict[str, str]:
    """Parse a table column walk keyed by a 6-octet MAC.  Returns {mac_str: value}.

    tail=False: MAC is the first 6 integers of the OID suffix (AP/radio tables).
    tail=True:  MAC is the last 6 integers of the OID suffix (client table).
    """
    prefix = base_oid + "."
    result: dict[str, str] = {}
    for oid, val in raw.items():
        if oid.startswith(prefix):
            parts = oid[len(prefix) :].split(".")
            if len(parts) >= 6:
                mac_parts = parts[-6:] if tail else parts[:6]
                try:
                    mac = ":".join(f"{int(b):02x}" for b in mac_parts)
                    result[mac] = val
                except (ValueError, TypeError):
                    pass
    return result


def _parse_radio_table(
    raw: dict[str, str], base_oid: str
) -> dict[tuple[str, int], str]:
    """Parse one radio-table column walk.  Returns {(mac_str, radio_idx): value}.

    Radio table OID index: mac_b0…mac_b5.radio_idx (7 integers).
    """
    prefix = base_oid + "."
    result: dict[tuple[str, int], str] = {}
    for oid, val in raw.items():
        if oid.startswith(prefix):
            parts = oid[len(prefix) :].split(".")
            if len(parts) >= 7:
                try:
                    mac = ":".join(f"{int(b):02x}" for b in parts[:6])
                    radio_idx = int(parts[6])
                    result[(mac, radio_idx)] = val
                except (ValueError, TypeError):
                    pass
    return result


def _derive_radio_type(channel: str | None) -> str | None:
    """Derive radio band from channel string.

    Aruba appends a suffix indicating channel width, not band:
      S = 80 MHz, E = 160 MHz (or 80+80), + = 40 MHz upper, - = 40 MHz lower
    Strip the suffix and classify by channel number:
      1–14  → 2.4 GHz
      36+   → 5 GHz
    """
    if not channel:
        return None
    stripped = channel.upper().rstrip("SPETM+-")
    try:
        ch_num = int(stripped)
    except ValueError:
        return None
    return "2.4 GHz" if 1 <= ch_num <= 14 else "5 GHz"


def _counter_rate(current: int, previous: int, dt: float) -> float | None:
    """Compute per-second rate from a 32-bit wrapping counter."""
    if dt <= 0:
        return None
    delta = (current - previous) % _MAX32
    return round(delta / dt, 1)


def _hex_to_mac(hex_str: str | None) -> str | None:
    """Normalize a hex BSSID string to 'aa:bb:cc:dd:ee:ff' format.

    Accepts '0x1c28afb46242', '1c 28 af b4 62 42', or '1c:28:af:b4:62:42'.
    """
    if not hex_str:
        return None
    s = hex_str.strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    else:
        s = s.replace(":", "").replace("-", "").replace(" ", "")
    s = s.lower()
    if len(s) != 12:
        return None
    try:
        return ":".join(s[i : i + 2] for i in range(0, 12, 2))
    except Exception:
        return None


def _ticks_to_seconds(v: str | None) -> int | None:
    """Parse a Timeticks centisecond string to integer seconds."""
    if v is None:
        return None
    try:
        return int(v) // 100
    except (ValueError, TypeError):
        return None


def _safe_walk(raw: Any) -> dict[str, str]:
    """Return raw walk dict, or {} for exceptions from asyncio.gather(return_exceptions=True)."""
    if isinstance(raw, Exception):
        _LOGGER.debug("SNMP walk failed: %s", raw)
        return {}
    return raw if isinstance(raw, dict) else {}


def _find_radio_for_bssid(
    client_bssid: str,
    radio_base_bssids: dict[tuple[str, int], str],
) -> tuple[str, int] | None:
    """Match a client BSSID to a (ap_mac, radio_idx) by upper nibble of last byte.

    Aruba assigns per-SSID BSSIDs by incrementing the lower nibble of the last
    MAC byte.  The base BSSID (radio_base_bssids) shares the same upper nibble,
    so masking with 0xF0 identifies which radio the client is on.
    """
    c_parts = client_bssid.split(":")
    if len(c_parts) != 6:
        return None
    try:
        c_last = int(c_parts[5], 16)
    except ValueError:
        return None
    for (ap_mac, radio_idx), base_bssid in radio_base_bssids.items():
        r_parts = base_bssid.split(":")
        if len(r_parts) != 6:
            continue
        if c_parts[:5] != r_parts[:5]:
            continue
        try:
            r_last = int(r_parts[5], 16)
        except ValueError:
            continue
        if (c_last & 0xF0) == (r_last & 0xF0):
            return (ap_mac, radio_idx)
    return None


# =============================================================================
# Coordinator
# =============================================================================


class ArubaAPCoordinator(DataUpdateCoordinator[ArubaClusterData]):
    """Coordinator that polls an Aruba Instant AP cluster via SNMP."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        community: str,
        snmp_port: int,
        snmp_version: str,
        update_seconds: int,
        mac_hostname_file: str = "",
        clients_mapped_only: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{host}",
            update_interval=timedelta(seconds=update_seconds),
        )
        self.host = host
        self.community = community
        self.snmp_port = snmp_port
        self.snmp_version = snmp_version
        self.mac_hostname_file = mac_hostname_file
        self.clients_mapped_only = clients_mapped_only
        self._mac_hostname_map: dict[str, str] = {}
        # (mac, radio_idx) → (tx_bytes, rx_bytes,
        #                      tx_total_f, tx_mgmt_f, tx_data_f,
        #                      rx_total_f, rx_data_f, rx_mgmt_f,
        #                      tx_dropped, rx_bad, phy_events, monotonic_time)
        self._prev_radio_counters: dict[
            tuple[str, int],
            tuple[int, int, int, int, int, int, int, int, int, int, int, float],
        ] = {}
        # client_mac → (tx_bytes, rx_bytes, tx_retries, rx_retries, monotonic_time)
        self._prev_client_counters: dict[str, tuple[int, int, int, int, float]] = {}
        # ap_mac → last reported boot time (held stable within tolerance)
        self._prev_ap_boot: dict[str, datetime] = {}

    async def _load_mac_hostname_file(self) -> dict[str, str]:
        """Load MAC→hostname mapping from a JSON file on disk."""
        if not self.mac_hostname_file:
            return {}

        def _read() -> dict[str, str]:
            def _normalize(mac: str) -> str:
                clean = mac.lower().replace(":", "").replace("-", "").replace(".", "")
                if len(clean) == 12:
                    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))
                return mac.lower()

            try:
                with open(self.mac_hostname_file, encoding="utf-8") as fh:
                    raw = json.load(fh)
                if not isinstance(raw, dict):
                    _LOGGER.warning(
                        "MAC hostname file %s must be a JSON object",
                        self.mac_hostname_file,
                    )
                    return {}
                return {
                    _normalize(k): str(v)
                    for k, v in raw.items()
                    if isinstance(v, str) and v.strip()
                }
            except FileNotFoundError:
                _LOGGER.debug("MAC hostname file not found: %s", self.mac_hostname_file)
                return {}
            except Exception as err:
                _LOGGER.warning(
                    "Failed to load MAC hostname file %s: %s",
                    self.mac_hostname_file,
                    err,
                )
                return {}

        return await self.hass.async_add_executor_job(_read)

    async def _walk(self, oid: str) -> dict[str, str]:
        """Shorthand for async_snmp_walk using this coordinator's SNMP settings."""
        return await async_snmp_walk(
            self.host,
            self.community,
            self.snmp_port,
            oid,
            snmp_version=self.snmp_version,
        )

    async def _async_update_data(self) -> ArubaClusterData:
        try:
            return await self._fetch_data()
        except Exception as err:
            _LOGGER.exception("Update failed for %s", self.host)
            raise UpdateFailed(str(err)) from err

    async def _fetch_data(self) -> ArubaClusterData:
        """Fetch all cluster data via parallel SNMP walks."""
        (
            ap_name_raw,
            ap_ip_raw,
            ap_model_raw,
            ap_serial_raw,
            ap_uptime_raw,
            ap_status_raw,
            ap_role_raw,
            ap_firmware_raw,
            ap_cpu_raw,
            ap_mem_free_raw,
            ap_mem_total_raw,
            radio_channel_raw,
            radio_txpow_raw,
            radio_clients_raw,
            radio_util_raw,
            radio_status_raw,
            radio_noise_floor_raw,
            radio_tx_total_frames_raw,
            radio_tx_mgmt_raw,
            radio_tx_data_frames_raw,
            radio_tx_bytes_raw,
            radio_tx_dropped_raw,
            radio_rx_total_frames_raw,
            radio_rx_data_frames_raw,
            radio_rx_bytes_raw,
            radio_rx_mgmt_raw,
            radio_rx_bad_raw,
            radio_phy_events_raw,
            radio_util64_raw,
            radio_bssid_raw,
            bss_ssid_raw,
            bss_bssid_raw,
            cl_ip_raw,
            cl_bssid_raw,
            cl_snr_raw,
            cl_tx_raw,
            cl_rx_raw,
            cl_tx_retries_raw,
            cl_rx_retries_raw,
            cl_phy_type_raw,
            cl_ht_mode_raw,
            cl_speed_raw,
            cl_rx_rate_raw,
            cl_uptime_raw,
            cl_hostname_raw,
            cl_os_raw,
        ) = await asyncio.gather(
            self._walk(OID_AP_NAME),
            self._walk(OID_AP_IP),
            self._walk(OID_AP_MODEL),
            self._walk(OID_AP_SERIAL),
            self._walk(OID_AP_UPTIME),
            self._walk(OID_AP_STATUS),
            self._walk(OID_AP_ROLE),
            self._walk(OID_AP_SW_VERSION),
            self._walk(OID_AP_CPU_USAGE),
            self._walk(OID_AP_MEM_FREE),
            self._walk(OID_AP_MEM_TOTAL),
            self._walk(OID_RADIO_CHANNEL),
            self._walk(OID_RADIO_TX_POWER),
            self._walk(OID_RADIO_CLIENTS),
            self._walk(OID_RADIO_UTILIZATION),
            self._walk(OID_RADIO_STATUS),
            self._walk(OID_RADIO_NOISE_FLOOR),
            self._walk(OID_RADIO_TX_TOTAL_FRAMES),
            self._walk(OID_RADIO_TX_MGMT),
            self._walk(OID_RADIO_TX_DATA_FRAMES),
            self._walk(OID_RADIO_TX_BYTES),
            self._walk(OID_RADIO_TX_DROPPED),
            self._walk(OID_RADIO_RX_TOTAL_FRAMES),
            self._walk(OID_RADIO_RX_DATA_FRAMES),
            self._walk(OID_RADIO_RX_BYTES),
            self._walk(OID_RADIO_RX_MGMT),
            self._walk(OID_RADIO_RX_BAD),
            self._walk(OID_RADIO_PHY_EVENTS),
            self._walk(OID_RADIO_UTILIZATION64),
            self._walk(OID_RADIO_BSSID),
            self._walk(OID_BSS_SSID),
            self._walk(OID_BSS_BSSID),
            self._walk(OID_CLIENT_IP),
            self._walk(OID_CLIENT_BSSID),
            self._walk(OID_CLIENT_SNR),
            self._walk(OID_CLIENT_TX_BYTES),
            self._walk(OID_CLIENT_RX_BYTES),
            self._walk(OID_CLIENT_TX_RETRIES),
            self._walk(OID_CLIENT_RX_RETRIES),
            self._walk(OID_CLIENT_PHY_TYPE),
            self._walk(OID_CLIENT_HT_MODE),
            self._walk(OID_CLIENT_SPEED),
            self._walk(OID_CLIENT_RX_RATE),
            self._walk(OID_CLIENT_UPTIME),
            self._walk(OID_CLIENT_HOSTNAME),
            self._walk(OID_CLIENT_OS),
            return_exceptions=True,
        )

        # ── AP table (indexed by MAC) ──────────────────────────────────────
        ap_names = _parse_mac_table(_safe_walk(ap_name_raw), OID_AP_NAME)
        ap_ips = _parse_mac_table(_safe_walk(ap_ip_raw), OID_AP_IP)
        ap_models = _parse_mac_table(_safe_walk(ap_model_raw), OID_AP_MODEL)
        ap_serials = _parse_mac_table(_safe_walk(ap_serial_raw), OID_AP_SERIAL)
        ap_uptimes = _parse_mac_table(_safe_walk(ap_uptime_raw), OID_AP_UPTIME)
        ap_statuses = _parse_mac_table(_safe_walk(ap_status_raw), OID_AP_STATUS)
        ap_roles = _parse_mac_table(_safe_walk(ap_role_raw), OID_AP_ROLE)
        ap_cpu = _parse_mac_table(_safe_walk(ap_cpu_raw), OID_AP_CPU_USAGE)
        ap_mem_free = _parse_mac_table(_safe_walk(ap_mem_free_raw), OID_AP_MEM_FREE)
        ap_mem_total = _parse_mac_table(_safe_walk(ap_mem_total_raw), OID_AP_MEM_TOTAL)

        # VC firmware (scalar walk)
        cluster_firmware = _first_value(_safe_walk(ap_firmware_raw))

        # ── Radio table (indexed by (MAC, radio_idx)) ──────────────────────
        radio_channels = _parse_radio_table(
            _safe_walk(radio_channel_raw), OID_RADIO_CHANNEL
        )
        radio_txpows = _parse_radio_table(
            _safe_walk(radio_txpow_raw), OID_RADIO_TX_POWER
        )
        radio_clients_map = _parse_radio_table(
            _safe_walk(radio_clients_raw), OID_RADIO_CLIENTS
        )
        radio_utils = _parse_radio_table(
            _safe_walk(radio_util_raw), OID_RADIO_UTILIZATION
        )
        radio_statuses = _parse_radio_table(
            _safe_walk(radio_status_raw), OID_RADIO_STATUS
        )
        radio_noise_floors = _parse_radio_table(
            _safe_walk(radio_noise_floor_raw), OID_RADIO_NOISE_FLOOR
        )
        radio_tx_total_frames = _parse_radio_table(
            _safe_walk(radio_tx_total_frames_raw), OID_RADIO_TX_TOTAL_FRAMES
        )
        radio_tx_mgmt = _parse_radio_table(
            _safe_walk(radio_tx_mgmt_raw), OID_RADIO_TX_MGMT
        )
        radio_tx_data_frames = _parse_radio_table(
            _safe_walk(radio_tx_data_frames_raw), OID_RADIO_TX_DATA_FRAMES
        )
        radio_tx_bytes = _parse_radio_table(
            _safe_walk(radio_tx_bytes_raw), OID_RADIO_TX_BYTES
        )
        radio_tx_dropped = _parse_radio_table(
            _safe_walk(radio_tx_dropped_raw), OID_RADIO_TX_DROPPED
        )
        radio_rx_total_frames = _parse_radio_table(
            _safe_walk(radio_rx_total_frames_raw), OID_RADIO_RX_TOTAL_FRAMES
        )
        radio_rx_data_frames = _parse_radio_table(
            _safe_walk(radio_rx_data_frames_raw), OID_RADIO_RX_DATA_FRAMES
        )
        radio_rx_bytes = _parse_radio_table(
            _safe_walk(radio_rx_bytes_raw), OID_RADIO_RX_BYTES
        )
        radio_rx_mgmt = _parse_radio_table(
            _safe_walk(radio_rx_mgmt_raw), OID_RADIO_RX_MGMT
        )
        radio_rx_bad = _parse_radio_table(
            _safe_walk(radio_rx_bad_raw), OID_RADIO_RX_BAD
        )
        radio_phy_events = _parse_radio_table(
            _safe_walk(radio_phy_events_raw), OID_RADIO_PHY_EVENTS
        )
        radio_util64 = _parse_radio_table(
            _safe_walk(radio_util64_raw), OID_RADIO_UTILIZATION64
        )

        # ── Discover all AP MACs and all (mac, radio_idx) keys ─────────────
        all_ap_macs = set(ap_names) | set(ap_statuses)
        all_radio_keys = set(radio_statuses) | set(radio_channels)

        now = time.monotonic()
        now_dt = dt_util.utcnow()

        # ── Build PerAPData per AP ─────────────────────────────────────────
        aps: dict[str, PerAPData] = {}
        for mac in sorted(all_ap_macs):
            ap_radio_indices = sorted(idx for (m, idx) in all_radio_keys if m == mac)

            radios: dict[int, RadioData] = {}
            for radio_idx in ap_radio_indices:
                key = (mac, radio_idx)
                status_raw = radio_statuses.get(key)
                is_up = str(status_raw) == "1" if status_raw is not None else False
                channel = radio_channels.get(key)

                # Noise floor is stored as positive magnitude; negate to get dBm
                nf_mag = _as_int(radio_noise_floors.get(key))
                noise_floor = -nf_mag if nf_mag is not None else None

                # Raw values (None when OID absent, 0 is a legitimate reading)
                tx_b_raw = _as_int(radio_tx_bytes.get(key))
                rx_b_raw = _as_int(radio_rx_bytes.get(key))
                tx_tot_f_raw = _as_int(radio_tx_total_frames.get(key))
                tx_mgmt_f_raw = _as_int(radio_tx_mgmt.get(key))
                tx_dat_f_raw = _as_int(radio_tx_data_frames.get(key))
                rx_tot_f_raw = _as_int(radio_rx_total_frames.get(key))
                rx_dat_f_raw = _as_int(radio_rx_data_frames.get(key))
                rx_mgmt_f_raw = _as_int(radio_rx_mgmt.get(key))
                tx_drp_raw = _as_int(radio_tx_dropped.get(key))
                rx_bad_raw = _as_int(radio_rx_bad.get(key))
                phy_evt_raw = _as_int(radio_phy_events.get(key))
                # Defaulted-to-0 values for counter rate arithmetic
                tx_b = tx_b_raw or 0
                rx_b = rx_b_raw or 0
                tx_tot_f = tx_tot_f_raw or 0
                tx_mgmt_f = tx_mgmt_f_raw or 0
                tx_dat_f = tx_dat_f_raw or 0
                rx_tot_f = rx_tot_f_raw or 0
                rx_dat_f = rx_dat_f_raw or 0
                rx_mgmt_f = rx_mgmt_f_raw or 0
                tx_drp = tx_drp_raw or 0
                rx_bad = rx_bad_raw or 0
                phy_evt = phy_evt_raw or 0

                # Compute rates from previous poll
                tx_bps = rx_bps = tx_drp_ps = rx_bad_ps = phy_evt_ps = None
                tx_tot_ps = tx_mgmt_ps = tx_dat_ps = None
                rx_tot_ps = rx_dat_ps = rx_mgmt_ps = None
                prev = self._prev_radio_counters.get(key)
                if prev is not None:
                    (
                        prev_tx_b,
                        prev_rx_b,
                        prev_tx_tot_f,
                        prev_tx_mgmt_f,
                        prev_tx_dat_f,
                        prev_rx_tot_f,
                        prev_rx_dat_f,
                        prev_rx_mgmt_f,
                        prev_tx_drp,
                        prev_rx_bad,
                        prev_phy_evt,
                        prev_time,
                    ) = prev
                    dt = now - prev_time
                    # round to integer B/s
                    tx_bps = (
                        round(v)
                        if (v := _counter_rate(tx_b, prev_tx_b, dt)) is not None
                        else None
                    )
                    rx_bps = (
                        round(v)
                        if (v := _counter_rate(rx_b, prev_rx_b, dt)) is not None
                        else None
                    )
                    tx_tot_ps = _counter_rate(tx_tot_f, prev_tx_tot_f, dt)
                    tx_mgmt_ps = _counter_rate(tx_mgmt_f, prev_tx_mgmt_f, dt)
                    tx_dat_ps = _counter_rate(tx_dat_f, prev_tx_dat_f, dt)
                    rx_tot_ps = _counter_rate(rx_tot_f, prev_rx_tot_f, dt)
                    rx_dat_ps = _counter_rate(rx_dat_f, prev_rx_dat_f, dt)
                    rx_mgmt_ps = _counter_rate(rx_mgmt_f, prev_rx_mgmt_f, dt)
                    tx_drp_ps = _counter_rate(tx_drp, prev_tx_drp, dt)
                    rx_bad_ps = _counter_rate(rx_bad, prev_rx_bad, dt)
                    phy_evt_ps = _counter_rate(phy_evt, prev_phy_evt, dt)

                self._prev_radio_counters[key] = (
                    tx_b,
                    rx_b,
                    tx_tot_f,
                    tx_mgmt_f,
                    tx_dat_f,
                    rx_tot_f,
                    rx_dat_f,
                    rx_mgmt_f,
                    tx_drp,
                    rx_bad,
                    phy_evt,
                    now,
                )

                radios[radio_idx] = RadioData(
                    status="on" if is_up else "off",
                    channel=channel,
                    tx_power_dbm=_as_int(radio_txpows.get(key)),
                    clients=_as_int(radio_clients_map.get(key)) or 0,
                    utilization_pct=_as_int(radio_utils.get(key)),
                    utilization_64_pct=_as_int(radio_util64.get(key)),
                    radio_type=_derive_radio_type(channel),
                    noise_floor_dbm=noise_floor,
                    tx_bytes=tx_b_raw,
                    rx_bytes=rx_b_raw,
                    tx_total_frames=tx_tot_f_raw,
                    tx_mgmt_frames=tx_mgmt_f_raw,
                    tx_data_frames=tx_dat_f_raw,
                    rx_total_frames=rx_tot_f_raw,
                    rx_data_frames=rx_dat_f_raw,
                    rx_mgmt_frames=rx_mgmt_f_raw,
                    tx_dropped=tx_drp_raw,
                    rx_bad_frames=rx_bad_raw,
                    phy_events=phy_evt_raw,
                    tx_bytes_per_sec=tx_bps,
                    rx_bytes_per_sec=rx_bps,
                    tx_total_per_sec=tx_tot_ps,
                    tx_mgmt_per_sec=tx_mgmt_ps,
                    tx_data_per_sec=tx_dat_ps,
                    rx_total_per_sec=rx_tot_ps,
                    rx_data_per_sec=rx_dat_ps,
                    rx_mgmt_per_sec=rx_mgmt_ps,
                    tx_dropped_per_sec=tx_drp_ps,
                    rx_bad_per_sec=rx_bad_ps,
                    phy_events_per_sec=phy_evt_ps,
                )

            total_clients = sum(r.clients for r in radios.values())

            uptime_hundredths = _as_int(ap_uptimes.get(mac))
            uptime_seconds = (
                uptime_hundredths // 100 if uptime_hundredths is not None else None
            )

            # Derive a *stable* boot time. `now_dt - uptime` jitters a few
            # seconds every poll, so hold the previous value unless it drifts
            # past tolerance (reboot / clock correction).
            boot_time: datetime | None = None
            if uptime_seconds is not None:
                boot_candidate = now_dt - timedelta(seconds=uptime_seconds)
                prev_boot = self._prev_ap_boot.get(mac)
                if (
                    prev_boot is not None
                    and abs((boot_candidate - prev_boot).total_seconds())
                    <= _BOOT_TIME_TOLERANCE_S
                ):
                    boot_time = prev_boot
                else:
                    boot_time = boot_candidate
                self._prev_ap_boot[mac] = boot_time

            status_val = ap_statuses.get(mac)
            ap_status = (
                "up"
                if str(status_val) == "1"
                else "down"
                if status_val is not None
                else None
            )

            aps[mac] = PerAPData(
                mac=mac,
                name=ap_names.get(mac),
                ip=ap_ips.get(mac),
                model=ap_models.get(mac),
                serial=ap_serials.get(mac),
                firmware=cluster_firmware,
                status=ap_status,
                uptime_seconds=uptime_seconds,
                boot_time=boot_time,
                role=ap_roles.get(mac),
                cpu_pct=_as_int(ap_cpu.get(mac)),
                mem_free_bytes=_as_int(ap_mem_free.get(mac)),
                mem_total_bytes=_as_int(ap_mem_total.get(mac)),
                radios=radios,
                total_clients=total_clients,
            )

        # ── MAC→hostname file ──────────────────────────────────────────────
        mac_hostname_map = await self._load_mac_hostname_file()
        self._mac_hostname_map = mac_hostname_map

        # ── BSS table: build BSSID → SSID map ─────────────────────────────
        # BSS table indexed by (AP_MAC, bss_idx), same structure as radio table
        bss_ssids_by_key = _parse_radio_table(_safe_walk(bss_ssid_raw), OID_BSS_SSID)
        bss_bssids_by_key = _parse_radio_table(_safe_walk(bss_bssid_raw), OID_BSS_BSSID)
        bssid_to_ssid: dict[str, str] = {}
        for key, bssid_hex in bss_bssids_by_key.items():
            bssid_norm = _hex_to_mac(bssid_hex)
            ssid = bss_ssids_by_key.get(key)
            if bssid_norm and ssid:
                bssid_to_ssid[bssid_norm] = ssid

        # ── Radio BSSID table: build exact base-BSSID → (ap_mac, radio_idx) ─
        radio_bssid_map = _parse_radio_table(
            _safe_walk(radio_bssid_raw), OID_RADIO_BSSID
        )
        # {(ap_mac, radio_idx): base_bssid_str}
        radio_base_bssids: dict[tuple[str, int], str] = {}
        for key, bssid_hex in radio_bssid_map.items():
            bssid_norm = _hex_to_mac(bssid_hex)
            if bssid_norm:
                radio_base_bssids[key] = bssid_norm

        # ── Client table ───────────────────────────────────────────────────
        cl_ips = _parse_mac_table(_safe_walk(cl_ip_raw), OID_CLIENT_IP, tail=True)
        cl_bssids = _parse_mac_table(
            _safe_walk(cl_bssid_raw), OID_CLIENT_BSSID, tail=True
        )
        cl_snrs = _parse_mac_table(_safe_walk(cl_snr_raw), OID_CLIENT_SNR, tail=True)
        cl_tx = _parse_mac_table(_safe_walk(cl_tx_raw), OID_CLIENT_TX_BYTES, tail=True)
        cl_rx = _parse_mac_table(_safe_walk(cl_rx_raw), OID_CLIENT_RX_BYTES, tail=True)
        cl_phy_types = _parse_mac_table(
            _safe_walk(cl_phy_type_raw), OID_CLIENT_PHY_TYPE, tail=True
        )
        cl_ht_modes = _parse_mac_table(
            _safe_walk(cl_ht_mode_raw), OID_CLIENT_HT_MODE, tail=True
        )
        cl_speeds = _parse_mac_table(
            _safe_walk(cl_speed_raw), OID_CLIENT_SPEED, tail=True
        )
        cl_uptimes = _parse_mac_table(
            _safe_walk(cl_uptime_raw), OID_CLIENT_UPTIME, tail=True
        )
        cl_hostnames = _parse_mac_table(
            _safe_walk(cl_hostname_raw), OID_CLIENT_HOSTNAME, tail=True
        )
        cl_os = _parse_mac_table(_safe_walk(cl_os_raw), OID_CLIENT_OS, tail=True)
        cl_tx_retries = _parse_mac_table(
            _safe_walk(cl_tx_retries_raw), OID_CLIENT_TX_RETRIES, tail=True
        )
        cl_rx_retries = _parse_mac_table(
            _safe_walk(cl_rx_retries_raw), OID_CLIENT_RX_RETRIES, tail=True
        )
        cl_rx_rates = _parse_mac_table(
            _safe_walk(cl_rx_rate_raw), OID_CLIENT_RX_RATE, tail=True
        )

        # Use BSSID presence as the anchor — only list fully-associated clients
        all_client_macs = set(cl_bssids) | set(cl_ips)

        # Build fresh counters dict — only keeps entries for currently-seen clients
        new_client_counters: dict[str, tuple[int, int, int, int, float]] = {}

        clients: list[dict[str, Any]] = []
        for mac in sorted(all_client_macs):
            entry: dict[str, Any] = {"mac": mac}
            hostname = cl_hostnames.get(mac)
            if mac_hostname_map.get(mac):
                entry["name"] = mac_hostname_map[mac]
            elif hostname and hostname.strip() and not hostname.startswith("0x"):
                entry["name"] = hostname.strip()
            if ip := cl_ips.get(mac):
                entry["ip"] = ip
            if bssid_raw_val := cl_bssids.get(mac):
                entry["ap_bssid"] = bssid_raw_val
                bssid_norm = _hex_to_mac(bssid_raw_val)
                if bssid_norm:
                    if ssid := bssid_to_ssid.get(bssid_norm):
                        entry["ssid"] = ssid
                    radio_info = _find_radio_for_bssid(bssid_norm, radio_base_bssids)
                    if radio_info:
                        ap_mac_r, radio_idx_r = radio_info
                        entry["radio_ap_mac"] = ap_mac_r
                        entry["radio_idx"] = radio_idx_r
                        if ap := aps.get(ap_mac_r):
                            if ap.name:
                                entry["ap_name"] = ap.name
                            radio = ap.radios.get(radio_idx_r)
                            if radio and radio.channel:
                                entry["channel"] = radio.channel
            snr_raw = _as_int(cl_snrs.get(mac))
            if snr_raw is not None:
                entry["snr_db"] = snr_raw
            tx = _as_int(cl_tx.get(mac))
            rx = _as_int(cl_rx.get(mac))
            tx_ret = _as_int(cl_tx_retries.get(mac))
            rx_ret = _as_int(cl_rx_retries.get(mac))
            if tx is not None and rx is not None:
                prev_cl = self._prev_client_counters.get(mac)
                if prev_cl is not None:
                    prev_tx, prev_rx, prev_tx_ret, prev_rx_ret, prev_ts = prev_cl
                    dt = now - prev_ts
                    if dt > 0:
                        tx_delta = tx - prev_tx
                        rx_delta = rx - prev_rx
                        # round to integer B/s
                        if tx_delta >= 0:
                            entry["tx_rate"] = round(tx_delta / dt)
                        if rx_delta >= 0:
                            entry["rx_rate"] = round(rx_delta / dt)
                        if tx_ret is not None:
                            entry["tx_retry_rate"] = _counter_rate(
                                tx_ret, prev_tx_ret, dt
                            )
                        if rx_ret is not None:
                            entry["rx_retry_rate"] = _counter_rate(
                                rx_ret, prev_rx_ret, dt
                            )
                new_client_counters[mac] = (tx, rx, tx_ret or 0, rx_ret or 0, now)
            phy_raw = _as_int(cl_phy_types.get(mac))
            ht_raw = _as_int(cl_ht_modes.get(mac))
            if phy_raw is not None or ht_raw is not None:
                entry["connection_type"] = _derive_connection_type(phy_raw, ht_raw)
            if ht_raw is not None:
                entry["ht_mode_raw"] = ht_raw
            if (speed := _as_int(cl_speeds.get(mac))) is not None:
                entry["speed_mbps"] = speed
            if (rx_rate := _as_int(cl_rx_rates.get(mac))) is not None:
                entry["rx_speed_mbps"] = rx_rate
            if (uptime_s := _ticks_to_seconds(cl_uptimes.get(mac))) is not None:
                entry["uptime_seconds"] = uptime_s
            os_str = cl_os.get(mac)
            if os_str and os_str.strip() and os_str.upper() != "NOFP":
                entry["os_type"] = os_str.strip()
            clients.append(entry)

        self._prev_client_counters = new_client_counters

        cluster_total_clients = sum(ap.total_clients for ap in aps.values())
        cluster_clients_by_radio_type: dict[str, int] = {}
        for ap in aps.values():
            for radio in ap.radios.values():
                if radio.radio_type:
                    cluster_clients_by_radio_type[radio.radio_type] = (
                        cluster_clients_by_radio_type.get(radio.radio_type, 0)
                        + radio.clients
                    )

        return ArubaClusterData(
            aps=aps,
            clients=clients,
            firmware=cluster_firmware,
            total_clients=cluster_total_clients,
            clients_by_radio_type=cluster_clients_by_radio_type,
        )


# =============================================================================
# Sensor descriptions
# =============================================================================


@dataclass(frozen=True)
class RadioSensorDescription:
    key: str
    name: str
    value_fn: Callable[[RadioData], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    icon: str = "mdi:wifi"
    icon_fn: Callable[[Any], str] | None = None
    enabled_default: bool = True


RADIO_SENSOR_DESCRIPTIONS: tuple[RadioSensorDescription, ...] = (
    RadioSensorDescription(
        "status",
        "Status",
        lambda r: r.status,
        icon_fn=lambda v: "mdi:wifi" if v == "on" else "mdi:wifi-off",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "channel", "Channel", lambda r: r.channel, icon="mdi:sine-wave"
    ),
    RadioSensorDescription(
        "tx_power",
        "TX Power",
        lambda r: r.tx_power_dbm,
        unit="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:antenna",
    ),
    RadioSensorDescription(
        "clients",
        "Clients",
        lambda r: r.clients,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:account-multiple",
    ),
    RadioSensorDescription(
        "utilization",
        "Utilization",
        lambda r: r.utilization_pct,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
    ),
    RadioSensorDescription(
        "radio_type", "Radio Type", lambda r: r.radio_type, icon="mdi:wifi-settings"
    ),
    RadioSensorDescription(
        "noise_floor",
        "Noise Floor",
        lambda r: r.noise_floor_dbm,
        unit="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal-off",
    ),
    RadioSensorDescription(
        "tx_rate",
        "TX Throughput",
        lambda r: r.tx_bytes_per_sec,
        unit=UnitOfDataRate.BYTES_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:upload-network",
    ),
    RadioSensorDescription(
        "rx_rate",
        "RX Throughput",
        lambda r: r.rx_bytes_per_sec,
        unit=UnitOfDataRate.BYTES_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:download-network",
    ),
    RadioSensorDescription(
        "tx_total_frame_rate",
        "TX Total Frame Rate",
        lambda r: r.tx_total_per_sec,
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transfer-up",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "tx_mgmt_frame_rate",
        "TX Mgmt Frame Rate",
        lambda r: r.tx_mgmt_per_sec,
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transfer-up",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "tx_data_frame_rate",
        "TX Data Frame Rate",
        lambda r: r.tx_data_per_sec,
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transfer-up",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "rx_total_frame_rate",
        "RX Total Frame Rate",
        lambda r: r.rx_total_per_sec,
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transfer-down",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "rx_data_frame_rate",
        "RX Data Frame Rate",
        lambda r: r.rx_data_per_sec,
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transfer-down",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "rx_mgmt_frame_rate",
        "RX Mgmt Frame Rate",
        lambda r: r.rx_mgmt_per_sec,
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transfer-down",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "tx_dropped_rate",
        "TX Dropped Rate",
        lambda r: r.tx_dropped_per_sec,
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:close-network",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "rx_bad_rate",
        "RX Bad Frame Rate",
        lambda r: r.rx_bad_per_sec,
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-circle-outline",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "phy_event_rate",
        "Interference Rate",
        lambda r: r.phy_events_per_sec,
        unit="events/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:wifi-alert",
        enabled_default=False,
    ),
    RadioSensorDescription(
        "utilization_64",
        "Utilization (64s avg)",
        lambda r: r.utilization_64_pct,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        enabled_default=False,
    ),
)


@dataclass(frozen=True)
class ClientSensorDescription:
    key: str
    name: str
    value_fn: Callable[[dict[str, Any]], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    icon: str = "mdi:devices"
    enabled_default: bool = True


CLIENT_SENSOR_DESCRIPTIONS: tuple[ClientSensorDescription, ...] = (
    ClientSensorDescription(
        "snr",
        "SNR",
        lambda c: c.get("snr_db"),
        unit="dB",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal",
    ),
    ClientSensorDescription(
        "tx_rate",
        "TX Throughput",
        lambda c: c.get("tx_rate"),
        unit=UnitOfDataRate.BYTES_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:upload-network",
    ),
    ClientSensorDescription(
        "rx_rate",
        "RX Throughput",
        lambda c: c.get("rx_rate"),
        unit=UnitOfDataRate.BYTES_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:download-network",
    ),
    ClientSensorDescription(
        "connection_type",
        "Connection Type",
        lambda c: c.get("connection_type"),
        icon="mdi:wifi-settings",
    ),
    ClientSensorDescription(
        "ht_mode",
        "Channel Width",
        lambda c: _HT_MODE_MHZ.get(c["ht_mode_raw"]) if c.get("ht_mode_raw") else None,
        unit="MHz",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-expand-horizontal",
        enabled_default=False,
    ),
    ClientSensorDescription(
        "speed",
        "TX Link Speed",
        lambda c: c.get("speed_mbps"),
        unit=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
    ),
    ClientSensorDescription(
        "connection_uptime",
        "Connection Uptime",
        lambda c: c.get("uptime_seconds"),
        unit=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        enabled_default=False,
    ),
    ClientSensorDescription(
        "ip", "IP Address", lambda c: c.get("ip"), icon="mdi:ip-network"
    ),
    ClientSensorDescription("ssid", "SSID", lambda c: c.get("ssid"), icon="mdi:wifi"),
    ClientSensorDescription(
        "channel",
        "Channel",
        lambda c: c.get("channel"),
        icon="mdi:sine-wave",
        enabled_default=False,
    ),
    ClientSensorDescription(
        "ap_name", "Access Point", lambda c: c.get("ap_name"), icon="mdi:access-point"
    ),
    ClientSensorDescription(
        "mac",
        "MAC Address",
        lambda c: c.get("mac"),
        icon="mdi:identifier",
        enabled_default=False,
    ),
    ClientSensorDescription(
        "name", "Name", lambda c: c.get("name"), icon="mdi:tag", enabled_default=False
    ),
    ClientSensorDescription(
        "os_type",
        "Device Type",
        lambda c: c.get("os_type"),
        icon="mdi:devices",
        enabled_default=False,
    ),
    ClientSensorDescription(
        "rx_speed",
        "RX Link Speed",
        lambda c: c.get("rx_speed_mbps"),
        unit=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        enabled_default=False,
    ),
    ClientSensorDescription(
        "tx_retry_rate",
        "TX Retry Rate",
        lambda c: c.get("tx_retry_rate"),
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:refresh-circle",
        enabled_default=False,
    ),
    ClientSensorDescription(
        "rx_retry_rate",
        "RX Retry Rate",
        lambda c: c.get("rx_retry_rate"),
        unit="frames/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:refresh-circle",
        enabled_default=False,
    ),
)


# =============================================================================
# Shared base entity
# =============================================================================


class ArubaBaseEntity(SensorEntity):
    """Shared base for all Aruba AP sensor entities."""

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


# =============================================================================
# AP sensor descriptions
# =============================================================================


@dataclass(frozen=True)
class APSensorDescription:
    key: str
    name: str
    value_fn: Callable[[PerAPData], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    icon: str = "mdi:access-point"
    icon_fn: Callable[[Any], str] | None = None
    extra_attrs_fn: Callable[[PerAPData], dict[str, Any]] | None = None
    enabled_default: bool = True


def _ap_status_attrs(ap: PerAPData) -> dict[str, Any]:
    attrs: dict[str, Any] = {"mac_address": ap.mac}
    if ap.ip:
        attrs["ip_address"] = ap.ip
    if ap.role:
        attrs["role"] = ap.role
    return attrs


def _ap_memory_usage(ap: PerAPData) -> int | None:
    if (
        ap.mem_total_bytes is None
        or ap.mem_total_bytes == 0
        or ap.mem_free_bytes is None
    ):
        return None
    used = ap.mem_total_bytes - ap.mem_free_bytes
    return round(100 * used / ap.mem_total_bytes)


@dataclass(frozen=True)
class ClusterSensorDescription:
    key: str
    name: str
    value_fn: Callable[[ArubaClusterData], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    icon: str = "mdi:access-point-network"
    enabled_default: bool = True


AP_SENSOR_DESCRIPTIONS: tuple[APSensorDescription, ...] = (
    APSensorDescription(
        "ap_status",
        "AP Status",
        lambda ap: ap.status,
        icon_fn=lambda v: "mdi:access-point" if v == "up" else "mdi:access-point-off",
        extra_attrs_fn=_ap_status_attrs,
        enabled_default=False,
    ),
    APSensorDescription(
        "total_clients",
        "Total Clients",
        lambda ap: ap.total_clients,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:account-multiple",
    ),
    APSensorDescription(
        "firmware", "Firmware", lambda ap: ap.firmware, icon="mdi:chip"
    ),
    APSensorDescription(
        "boot_time",
        "Started",
        lambda ap: ap.boot_time,
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
    ),
    APSensorDescription(
        "uptime",
        "Uptime",
        lambda ap: ap.uptime_seconds,
        unit=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        # Increments every poll → a recorder row per poll. Superseded by the
        # stable "Started" timestamp; off by default to cut recorder volume.
        enabled_default=False,
    ),
    APSensorDescription(
        "cpu_usage",
        "CPU Usage",
        lambda ap: ap.cpu_pct,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cpu-64-bit",
    ),
    APSensorDescription(
        "memory_usage",
        "Memory Usage",
        _ap_memory_usage,
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:memory",
    ),
)


# =============================================================================
# AP-level sensors  (one device per physical AP)
# =============================================================================


class ArubaAPBaseEntity(ArubaBaseEntity):
    """Base for sensors attached to a specific AP device."""

    def __init__(
        self, coordinator: ArubaAPCoordinator, entry_id: str, ap_mac: str
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._ap_mac = ap_mac
        ap_data = coordinator.data.aps.get(ap_mac) if coordinator.data else None
        mac_short = _mac_slug(ap_mac)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{mac_short}")},
            name=(ap_data.name if ap_data else None) or f"Aruba AP {ap_mac}",
            manufacturer="Aruba Networks",
            model=ap_data.model if ap_data else None,
            sw_version=ap_data.firmware if ap_data else None,
            serial_number=ap_data.serial if ap_data else None,
            via_device=(DOMAIN, f"{entry_id}_cluster"),
        )

    def _ap_data(self) -> PerAPData | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.aps.get(self._ap_mac)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.data:
            self._update_device_info()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_device_info()
        self.async_write_ha_state()

    @callback
    def _update_device_info(self) -> None:
        ap = self._ap_data()
        if not ap:
            return
        mac_short = _mac_slug(self._ap_mac)
        dev_reg = device_registry.async_get(self.hass)
        device_entry = dev_reg.async_get_device(
            identifiers={(DOMAIN, f"{self._entry_id}_{mac_short}")}
        )
        if device_entry:
            dev_reg.async_update_device(
                device_entry.id,
                name=ap.name or f"Aruba AP {self._ap_mac}",
                model=ap.model,
                sw_version=ap.firmware,
                serial_number=ap.serial,
            )


class APSensor(ArubaAPBaseEntity):
    """One sensor for one attribute of one AP."""

    def __init__(
        self,
        coordinator: ArubaAPCoordinator,
        entry_id: str,
        ap_mac: str,
        description: APSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, ap_mac)
        self._description = description
        self._attr_name = description.name
        mac_short = _mac_slug(ap_mac)
        self._attr_unique_id = f"{entry_id}_{mac_short}_{description.key}"
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_icon = description.icon
        self._attr_entity_registry_enabled_default = description.enabled_default

    @property
    def native_value(self) -> Any:
        ap = self._ap_data()
        return None if ap is None else self._description.value_fn(ap)

    @property
    def icon(self) -> str | None:
        if self._description.icon_fn:
            return self._description.icon_fn(self.native_value)
        return self._attr_icon

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._description.extra_attrs_fn is None:
            return {}
        ap = self._ap_data()
        return self._description.extra_attrs_fn(ap) if ap else {}


# =============================================================================
# Cluster sensors  (one device for the whole cluster)
# =============================================================================


class ClusterSensor(ArubaBaseEntity):
    """Sensor attached to the cluster-level virtual device."""

    def __init__(
        self,
        coordinator: ArubaAPCoordinator,
        entry_id: str,
        description: ClusterSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{entry_id}_cluster_{description.key}"
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_icon = description.icon
        self._attr_entity_registry_enabled_default = description.enabled_default
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_cluster")},
            name="Aruba Cluster",
            manufacturer="Aruba Networks",
            sw_version=coordinator.data.firmware if coordinator.data else None,
        )

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return self._description.value_fn(self.coordinator.data)


# =============================================================================
# Radio sensors  (one device per radio, via_device → AP)
# =============================================================================


class RadioSensor(ArubaBaseEntity):
    """One sensor for one attribute of one radio on one AP."""

    def __init__(
        self,
        coordinator: ArubaAPCoordinator,
        entry_id: str,
        ap_mac: str,
        radio_index: int,
        description: RadioSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._ap_mac = ap_mac
        self._radio_index = radio_index
        self._description = description
        self._attr_name = description.name
        mac_short = _mac_slug(ap_mac)
        self._attr_unique_id = (
            f"{entry_id}_{mac_short}_radio_{radio_index}_{description.key}"
        )
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_icon = description.icon
        self._attr_entity_registry_enabled_default = description.enabled_default

        # Include AP name in the radio device name
        ap_data = coordinator.data.aps.get(ap_mac) if coordinator.data else None
        ap_name = (ap_data.name if ap_data else None) or ap_mac
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{mac_short}_radio_{radio_index}")},
            name=f"{ap_name} / Radio {radio_index}",
            manufacturer="Aruba Networks",
            via_device=(DOMAIN, f"{entry_id}_{mac_short}"),
        )

    def _radio_data(self) -> RadioData | None:
        if not self.coordinator.data:
            return None
        ap = self.coordinator.data.aps.get(self._ap_mac)
        return ap.radios.get(self._radio_index) if ap else None

    @property
    def native_value(self) -> Any:
        radio = self._radio_data()
        return None if radio is None else self._description.value_fn(radio)

    @property
    def icon(self) -> str | None:
        if self._description.icon_fn:
            return self._description.icon_fn(self.native_value)
        return self._attr_icon


# =============================================================================
# Client sensors  (one device per client)
# =============================================================================


def _derive_connection_type(phy_type: int | None, ht_mode: int | None) -> str | None:
    """Combine ArubaPhyType + ArubaHTMode into a human-readable connection type.

    Aruba separates band (PHY type) from protocol tier (HT mode), but the UI
    combines them (e.g. dot11a + ht40 → "802.11an").
    """
    if phy_type is None:
        return None
    if phy_type == 5:
        return "wired"
    if phy_type == 6:
        return "802.11ax (Wi-Fi 6E)"  # always 6 GHz ax

    is_5ghz = phy_type in (1, 4)  # dot11a or dot11ag
    is_24ghz = phy_type in (2, 3, 4)  # dot11b, dot11g, or dot11ag

    if ht_mode in (9, 10, 11, 12, 13):  # HE = 802.11ax
        return "802.11ax (Wi-Fi 6)" if is_5ghz else "802.11ax"
    if ht_mode in (4, 5, 6, 7, 8):  # VHT = 802.11ac
        return "802.11ac"
    if ht_mode in (2, 3):  # HT = 802.11n
        if is_5ghz and not is_24ghz:
            return "802.11an"
        if is_24ghz and not is_5ghz:
            return "802.11gn"
        return "802.11n"  # dot11ag — could be either band

    # Legacy (ht_mode == 1 or unknown)
    return CLIENT_PHY_TYPE_MAP.get(phy_type)


def _client_display_name(client: dict[str, Any] | None, mac: str) -> str:
    """Return 'Name / mac' when a textual name is known, otherwise just the MAC."""
    name = client.get("name") if client else None
    return f"{name} / {mac}" if name else mac


class ClientSensor(ArubaBaseEntity):
    """One sensor for one attribute of one WiFi client."""

    def __init__(
        self,
        coordinator: ArubaAPCoordinator,
        entry_id: str,
        mac: str,
        description: ClientSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._entry_id = entry_id
        self._description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{entry_id}_client_{_mac_slug(mac)}_{description.key}"
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_icon = description.icon
        self._attr_entity_registry_enabled_default = description.enabled_default
        client = self._find_client(coordinator)
        name = client.get("name") if client else None
        mac_slug = _mac_slug(mac)
        if name:
            self.entity_id = f"sensor.{slugify(name)}_{description.key}"
        else:
            self.entity_id = f"sensor.client_{mac_slug}_{description.key}"
        identifiers = {(DOMAIN, f"{entry_id}_client_{_mac_slug(mac)}")}
        name = _client_display_name(client, mac)
        via_device = self._radio_via_device(client)
        if via_device is None:
            self._attr_device_info = DeviceInfo(identifiers=identifiers, name=name)
        else:
            self._attr_device_info = DeviceInfo(
                identifiers=identifiers, name=name, via_device=via_device
            )

    def _find_client(
        self, coordinator: ArubaAPCoordinator | None = None
    ) -> dict[str, Any] | None:
        coord = coordinator or self.coordinator
        if not coord.data:
            return None
        return next((c for c in coord.data.clients if c["mac"] == self._mac), None)

    def _radio_via_device(
        self, client: dict[str, Any] | None
    ) -> tuple[str, str] | None:
        """Return the (domain, identifier) of the radio this client is on, or None."""
        if client is None:
            return None
        ap_mac = client.get("radio_ap_mac")
        radio_idx = client.get("radio_idx")
        if ap_mac is None or radio_idx is None:
            return None
        return (DOMAIN, f"{self._entry_id}_{_mac_slug(ap_mac)}_radio_{radio_idx}")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._find_client() is not None

    @property
    def native_value(self) -> Any:
        client = self._find_client()
        return None if client is None else self._description.value_fn(client)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_client_device_info()
        self.async_write_ha_state()

    @callback
    def _update_client_device_info(self) -> None:
        client = self._find_client()
        if client is None:
            return
        dev_reg = device_registry.async_get(self.hass)
        device_entry = dev_reg.async_get_device(
            identifiers={(DOMAIN, f"{self._entry_id}_client_{_mac_slug(self._mac)}")}
        )
        if device_entry is None:
            return

        update_kwargs: dict[str, Any] = {}

        name = _client_display_name(client, self._mac)
        if device_entry.name != name:
            update_kwargs["name"] = name

        # Resolve current radio device id for via_device (handles roaming)
        via_device_id: str | None = None
        radio_via = self._radio_via_device(client)
        if radio_via:
            radio_entry = dev_reg.async_get_device(identifiers={radio_via})
            if radio_entry:
                via_device_id = radio_entry.id
        if device_entry.via_device_id != via_device_id:
            update_kwargs["via_device_id"] = via_device_id

        if update_kwargs:
            dev_reg.async_update_device(device_entry.id, **update_kwargs)


# =============================================================================
# Platform setup
# =============================================================================


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Aruba AP sensor entities for all APs in the cluster."""
    coordinator: ArubaAPCoordinator = hass.data[DOMAIN][entry.entry_id]
    entry_id = entry.entry_id

    known_aps: set[str] = set()  # AP MACs already registered
    known_radios: set[tuple[str, int]] = set()  # (mac, radio_idx) already registered
    known_client_macs: set[str] = set()
    known_radio_types: set[str] = set()

    # Cluster-level total-clients sensor (always present)
    async_add_entities(
        [
            ClusterSensor(
                coordinator,
                entry_id,
                ClusterSensorDescription(
                    "total_clients",
                    "Total Clients",
                    lambda data: data.total_clients,
                    state_class=SensorStateClass.MEASUREMENT,
                    icon="mdi:account-multiple",
                ),
            )
        ]
    )

    def _radio_type_fn(rt: str) -> Callable[[ArubaClusterData], int]:
        return lambda data: data.clients_by_radio_type.get(rt, 0)

    @callback
    def _add_cluster_radio_type_sensors() -> None:
        if not coordinator.data:
            return
        new_entities: list[SensorEntity] = []
        for radio_type in coordinator.data.clients_by_radio_type:
            if radio_type not in known_radio_types:
                known_radio_types.add(radio_type)
                rt_key = radio_type.lower().replace(" ", "_").replace(".", "")
                new_entities.append(
                    ClusterSensor(
                        coordinator,
                        entry_id,
                        ClusterSensorDescription(
                            f"clients_{rt_key}",
                            f"{radio_type} Clients",
                            _radio_type_fn(radio_type),
                            state_class=SensorStateClass.MEASUREMENT,
                            icon="mdi:account-multiple",
                        ),
                    )
                )
        if new_entities:
            async_add_entities(new_entities)

    _add_cluster_radio_type_sensors()
    entry.async_on_unload(
        coordinator.async_add_listener(_add_cluster_radio_type_sensors)
    )

    @callback
    def _add_new_aps() -> None:
        if not coordinator.data:
            return
        new_entities: list[SensorEntity] = []
        for ap_mac, ap_data in coordinator.data.aps.items():
            if ap_mac not in known_aps:
                known_aps.add(ap_mac)
                new_entities.extend(
                    [
                        APSensor(coordinator, entry_id, ap_mac, desc)
                        for desc in AP_SENSOR_DESCRIPTIONS
                    ]
                )
            for radio_idx in ap_data.radios:
                key = (ap_mac, radio_idx)
                if key not in known_radios:
                    known_radios.add(key)
                    for desc in RADIO_SENSOR_DESCRIPTIONS:
                        new_entities.append(
                            RadioSensor(coordinator, entry_id, ap_mac, radio_idx, desc)
                        )
        if new_entities:
            async_add_entities(new_entities)

    _add_new_aps()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_aps))

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
        new_entities: list[SensorEntity] = []
        for mac in new_macs:
            known_client_macs.add(mac)
            for desc in CLIENT_SENSOR_DESCRIPTIONS:
                new_entities.append(ClientSensor(coordinator, entry_id, mac, desc))
        async_add_entities(new_entities)

    _add_new_clients()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_clients))
