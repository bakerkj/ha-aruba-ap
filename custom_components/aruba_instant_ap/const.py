# Copyright (c) 2026 Kenneth Baker <bakerkj@umich.edu>
# All rights reserved.

"""Constants for Aruba Instant AP integration."""

from typing import Final

DOMAIN: Final = "aruba_instant_ap"

# Config entry keys
CONF_HOST: Final = "host"
CONF_COMMUNITY: Final = "community"
CONF_SNMP_PORT: Final = "snmp_port"

DEFAULT_SNMP_PORT: Final = 161
CONF_MAC_HOSTNAME_FILE: Final = "mac_hostname_file"
CONF_UPDATE_INTERVAL: Final = "update_interval"
DEFAULT_UPDATE_INTERVAL: Final = 60

# Aruba Networks Enterprise OID: 1.3.6.1.4.1.14823
# Aruba Instant (AI-MIB) base: 1.3.6.1.4.1.14823.2.3.3.1
_AI_BASE = "1.3.6.1.4.1.14823.2.3.3.1"

# ── Virtual Controller scalars (cluster-wide, not per-AP) ────────────────────
# These are under .1.X.0 and apply to the whole cluster.
OID_VC_NAME: Final = f"{_AI_BASE}.1.2.0"  # Cluster name (scalar, use with GET)
OID_VC_FW: Final = f"{_AI_BASE}.1.4.0"  # Firmware version (scalar, use with GET)
OID_VC_IP: Final = f"{_AI_BASE}.1.5.0"  # Virtual Controller IP (scalar)

# ── AP Table (_AI_BASE.2.1.1) ────────────────────────────────────────────────
# Indexed by AP MAC address (6-octet OID suffix).
# Observed from AOS-8.13.x walk of ap.keneli.org (5-AP cluster).
_AP_TABLE: Final = f"{_AI_BASE}.2.1.1"
OID_AP_MAC: Final = f"{_AP_TABLE}.1"  # AP MAC address (hex string '0x...')
OID_AP_NAME: Final = f"{_AP_TABLE}.2"  # AP name / location label
OID_AP_IP: Final = f"{_AP_TABLE}.3"  # AP IP address
OID_AP_SERIAL: Final = f"{_AP_TABLE}.4"  # Serial number
# col 5: model OID (e.g. '1.3.6.1.4.1.14823.1.2.107')
OID_AP_MODEL: Final = f"{_AP_TABLE}.6"  # Model number string (e.g. '515', '367')
OID_AP_CPU_USAGE: Final = f"{_AP_TABLE}.7"  # CPU utilization (%): aiAPCPUUtilization
OID_AP_MEM_FREE: Final = f"{_AP_TABLE}.8"  # Memory free (bytes): aiAPMemoryFree
OID_AP_UPTIME: Final = f"{_AP_TABLE}.9"  # Uptime in hundredths of seconds: aiAPUptime
OID_AP_MEM_TOTAL: Final = f"{_AP_TABLE}.10"  # Memory total (bytes): aiAPTotalMemory
OID_AP_STATUS: Final = f"{_AP_TABLE}.11"  # AP status: 1=up
# col 12: aiAPHwopmode — HW opmode enum (default/rsdb/dual5g/split5g variants)
OID_AP_ROLE: Final = f"{_AP_TABLE}.13"  # Role: 'cluster conductor'/'cluster member'

# Firmware: walk the parent OID so _first_value() retrieves the .0 scalar
OID_AP_SW_VERSION: Final = f"{_AI_BASE}.1.4"  # walks to .1.4.0 = cluster firmware

# ── Radio Table (_AI_BASE.2.2.1) ─────────────────────────────────────────────
# Indexed by (AP MAC address, radio index). Last OID integer = radio index.
# Observed from AOS-8.13.x walk of ap.keneli.org (5-AP cluster).
_RADIO_TABLE: Final = f"{_AI_BASE}.2.2.1"
# col 1: aiRadioAPMACAddress (INDEX)
# col 2: aiRadioIndex (INDEX)
# col 3: aiRadioMACAddress — radio MAC address (used as base BSSID)
OID_RADIO_BSSID: Final = (
    f"{_RADIO_TABLE}.3"  # Radio MAC / base BSSID: aiRadioMACAddress
)
OID_RADIO_CHANNEL: Final = f"{_RADIO_TABLE}.4"  # Channel string: aiRadioChannel
OID_RADIO_TX_POWER: Final = f"{_RADIO_TABLE}.5"  # TX power (dBm): aiRadioTransmitPower
# col 6: aiRadioNoiseFloor — MIB says "in dBm" but firmware returns positive magnitude; negate
OID_RADIO_NOISE_FLOOR: Final = (
    f"{_RADIO_TABLE}.6"  # Noise floor magnitude (negate for dBm)
)
OID_RADIO_UTILIZATION: Final = (
    f"{_RADIO_TABLE}.7"  # Channel utilization 4s avg (%): aiRadioUtilization4
)
OID_RADIO_UTILIZATION64: Final = (
    f"{_RADIO_TABLE}.8"  # Channel utilization 64s avg (%): aiRadioUtilization64
)
OID_RADIO_TX_TOTAL_FRAMES: Final = (
    f"{_RADIO_TABLE}.9"  # TX total frames (Counter32): aiRadioTxTotalFrames
)
OID_RADIO_TX_MGMT: Final = (
    f"{_RADIO_TABLE}.10"  # TX management frames (Counter32): aiRadioTxMgmtFrames
)
OID_RADIO_TX_DATA_FRAMES: Final = (
    f"{_RADIO_TABLE}.11"  # TX data frames (Counter32): aiRadioTxDataFrames
)
OID_RADIO_TX_BYTES: Final = (
    f"{_RADIO_TABLE}.12"  # TX data bytes (Counter32): aiRadioTxDataBytes
)
OID_RADIO_TX_DROPPED: Final = (
    f"{_RADIO_TABLE}.13"  # TX dropped frames (Counter32): aiRadioTxDrops
)
OID_RADIO_RX_TOTAL_FRAMES: Final = (
    f"{_RADIO_TABLE}.14"  # RX total frames (Counter32): aiRadioRxTotalFrames
)
OID_RADIO_RX_DATA_FRAMES: Final = (
    f"{_RADIO_TABLE}.15"  # RX data frames (Counter32): aiRadioRxDataFrames
)
OID_RADIO_RX_BYTES: Final = (
    f"{_RADIO_TABLE}.16"  # RX data bytes (Counter32): aiRadioRxDataBytes
)
OID_RADIO_RX_MGMT: Final = (
    f"{_RADIO_TABLE}.17"  # RX management frames (Counter32): aiRadioRxMgmtFrames
)
OID_RADIO_RX_BAD: Final = (
    f"{_RADIO_TABLE}.18"  # RX bad frames (Counter32): aiRadioRxBad
)
OID_RADIO_PHY_EVENTS: Final = f"{_RADIO_TABLE}.19"  # Frames not received due to interference (Counter32): aiRadioPhyEvents
OID_RADIO_STATUS: Final = f"{_RADIO_TABLE}.20"  # Radio status: 1=up: aiRadioStatus
OID_RADIO_CLIENTS: Final = f"{_RADIO_TABLE}.21"  # Clients per radio: aiRadioClientNum
OID_RADIO_TYPE: Final = ""  # Not in MIB; derive from channel string

# ── BSS/SSID Table (_AI_BASE.2.3.1) ─────────────────────────────────────────
# Indexed by (AP MAC, bss_idx). Each BSS entry is one SSID on one radio.
# Confirmed from AOS-8.13.x walk of ap.keneli.org.
_BSS_TABLE: Final = f"{_AI_BASE}.2.3.1"
# col 1: AP MAC address
# col 2: BSS index (serial 0..N, not the physical radio index)
OID_BSS_SSID: Final = f"{_BSS_TABLE}.3"  # SSID name string
OID_BSS_BSSID: Final = f"{_BSS_TABLE}.4"  # BSSID (Hex-STRING) for this BSS
# cols 5-10: per-BSS traffic counters

# ── Client Table (_AI_BASE.2.4.1) ─────────────────────────────────────────────
# Indexed by client MAC address (6-octet OID suffix). 115 entries observed.
# Confirmed from AOS-8.13.x walk of ap.keneli.org.
_CLIENT_TABLE: Final = f"{_AI_BASE}.2.4.1"
OID_CLIENT_BSSID: Final = (
    f"{_CLIENT_TABLE}.2"  # Associated BSSID: aiClientWlanMACAddress
)
OID_CLIENT_IP: Final = f"{_CLIENT_TABLE}.3"  # Client IP address: aiClientIPAddress
# col 4: aiClientAPIPAddress — associated AP IP address
OID_CLIENT_HOSTNAME: Final = f"{_CLIENT_TABLE}.5"  # Client hostname: aiClientName
OID_CLIENT_OS: Final = f"{_CLIENT_TABLE}.6"  # OS/device type string (e.g. 'Android', 'iPhone'): aiClientOperatingSystem
OID_CLIENT_SNR: Final = f"{_CLIENT_TABLE}.7"  # Signal-to-noise ratio (dB): aiClientSNR
# col 8: aiClientTxDataFrames — TX data frames (Counter32)
OID_CLIENT_TX_BYTES: Final = (
    f"{_CLIENT_TABLE}.9"  # TX bytes (Counter64): aiClientTxDataBytes
)
OID_CLIENT_TX_RETRIES: Final = (
    f"{_CLIENT_TABLE}.10"  # TX retry frames (Counter32): aiClientTxRetries
)
OID_CLIENT_SPEED: Final = f"{_CLIENT_TABLE}.11"  # TX link rate (Mbps): aiClientTxRate
# col 12: aiClientRxDataFrames — RX data frames (Counter32)
OID_CLIENT_RX_BYTES: Final = (
    f"{_CLIENT_TABLE}.13"  # RX bytes (Counter64): aiClientRxDataBytes
)
OID_CLIENT_RX_RETRIES: Final = (
    f"{_CLIENT_TABLE}.14"  # RX retry frames (Counter32): aiClientRxRetries
)
OID_CLIENT_RX_RATE: Final = f"{_CLIENT_TABLE}.15"  # RX link rate (Mbps): aiClientRxRate
OID_CLIENT_UPTIME: Final = (
    f"{_CLIENT_TABLE}.16"  # Connection uptime (Timeticks): aiClientUptime
)
OID_CLIENT_PHY_TYPE: Final = f"{_CLIENT_TABLE}.17"  # PHY type integer: aiClientPhyType
OID_CLIENT_HT_MODE: Final = f"{_CLIENT_TABLE}.18"  # HT/VHT/HE mode enum: aiClientHtMode

# ── Standard MIBs (RFC 1213 / RFC 3418) ─────────────────────────────────────
OID_SYS_DESCR: Final = "1.3.6.1.2.1.1.1.0"  # sysDescr
OID_SYS_NAME: Final = "1.3.6.1.2.1.1.5.0"  # sysName
OID_SYS_UPTIME: Final = "1.3.6.1.2.1.1.3.0"  # sysUpTime (TimeTicks)

# aiClientPhyType (ArubaPhyType) integer → band/medium
# Note: protocol tier (n/ac/ax) is encoded separately in aiClientHtMode
CLIENT_PHY_TYPE_MAP: Final = {
    1: "802.11a",  # dot11a  — 5 GHz legacy
    2: "802.11b",  # dot11b  — 2.4 GHz legacy
    3: "802.11g",  # dot11g  — 2.4 GHz
    4: "802.11a/g",  # dot11ag — dual-band a/g
    5: "wired",  # wired
    6: "802.11ax (6 GHz)",  # dot11ax6ghz — Wi-Fi 6E
}

# aiClientHtMode (ArubaHTMode) integer → channel-width/protocol tier
CLIENT_HT_MODE_MAP: Final = {
    1: "legacy",
    2: "HT20",
    3: "HT40",
    4: "VHT20",
    5: "VHT40",
    6: "VHT80",
    7: "VHT160",
    8: "VHT80+80",
    9: "HE20",
    10: "HE40",
    11: "HE80",
    12: "HE160",
    13: "HE80+80",
}

# Radio type derived from channel string prefix/suffix when OID not available
# '100S', '36S', '6E' etc → 5 GHz or 6 GHz; small integers → 2.4 GHz
RADIO_TYPE_MAP: Final = {
    1: "802.11a",
    2: "802.11g",
    3: "802.11n",
    4: "802.11ac",
    5: "802.11ax (Wi-Fi 6)",
    6: "802.11ax (Wi-Fi 6E)",
}
