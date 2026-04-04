4# Aruba Instant AP — Home Assistant Integration

Monitors an Aruba Instant AP cluster via SNMP and exposes per-AP, per-radio, and
per-client sensors in Home Assistant.

## Features

- **Per-AP sensors** — one device per physical access point
- **Per-radio sensors** — one device per radio per AP, linked to its parent AP
- **Per-client sensors** — one device per associated WiFi client, linked to its
  radio

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations → Custom repositories**
3. Add `https://github.com/bakerkj/ha-aruba-ap` as an **Integration**
4. Search for **Aruba Instant AP** and install it
5. Restart Home Assistant

### Manual

Copy `custom_components/aruba_instant_ap` into your Home Assistant
`custom_components` directory and restart.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration →
Aruba Instant AP**.

| Field             | Description                                                           |
| ----------------- | --------------------------------------------------------------------- |
| Host              | IP address or hostname of the virtual controller                      |
| SNMP Community    | SNMP v2c community string (default: `public`)                         |
| SNMP Port         | UDP port (default: `161`)                                             |
| SNMP Version      | `v2c` (default) or `v1`                                               |
| Update interval   | Poll interval in seconds (default: `60`, minimum: `10`)               |
| MAC hostname file | Path to a JSON file mapping MAC addresses to display names (optional) |

All settings can be changed later via **Settings → Devices & Services → Aruba
Instant AP → Reconfigure**.

### MAC hostname file

A JSON object mapping MAC addresses to display names. The mapping file takes
priority over hostnames reported by Aruba.

Several MAC formats are accepted:

```json
{
  "aa:bb:cc:dd:ee:ff": "Alice's laptop",
  "AABBCCDDEEFF": "printer",
  "11-22-33-44-55-66": "smart-tv"
}
```

## Sensors

### Per-AP

| Sensor        | Description                                                |
| ------------- | ---------------------------------------------------------- |
| AP Status     | `up` or `down`, with IP, model, serial, role as attributes |
| Total Clients | Number of clients currently associated across all radios   |
| Firmware      | Cluster firmware version                                   |
| Uptime        | AP uptime in seconds                                       |
| CPU Usage     | CPU utilization (%)                                        |
| Memory Usage  | Memory utilization (%)                                     |

### Per-radio

| Sensor                | Description                                    |
| --------------------- | ---------------------------------------------- |
| Status                | `on` or `off`                                  |
| Channel               | Active channel string (e.g. `36`, `6`, `100S`) |
| Radio Type            | Derived band (e.g. `2.4 GHz`, `5 GHz`)         |
| TX Power              | Transmit power (dBm)                           |
| Clients               | Number of associated clients                   |
| Utilization           | Channel utilization 4s average (%)             |
| Utilization (64s avg) | Channel utilization 64s average (%)            |
| Noise Floor           | Noise floor (dBm)                              |
| TX / RX Throughput    | Bytes per second                               |
| TX / RX Frame rates   | Total, data, and management frames per second  |
| TX Dropped Rate       | Dropped frames per second                      |
| RX Bad Frame Rate     | Bad frames per second                          |
| Interference Rate     | Frames lost to interference per second         |

### Per-client

| Sensor             | Description                                                 |
| ------------------ | ----------------------------------------------------------- |
| SNR                | Signal-to-noise ratio (dB)                                  |
| Connection Type    | e.g. `802.11ac`, `802.11ax (Wi-Fi 6)`                       |
| Channel Width      | e.g. `HT40`, `VHT80`, `HE80`                                |
| TX / RX Link Speed | Link rate (Mbps)                                            |
| TX / RX Throughput | Bytes per second                                            |
| TX / RX Retry Rate | Retry frames per second                                     |
| Connection Uptime  | Time associated (seconds)                                   |
| IP Address         | Client IP address                                           |
| SSID               | Associated SSID                                             |
| Channel            | Associated channel                                          |
| Access Point       | Name of the AP the client is on                             |
| MAC Address        | Client MAC address                                          |
| Name               | Display name (from mapping file or Aruba hostname)          |
| Device Type        | OS/device type reported by Aruba (e.g. `iPhone`, `Android`) |

## Requirements

- Aruba Instant (AOS-8) cluster with SNMP v2c enabled
- Home Assistant 2026.4 or later
