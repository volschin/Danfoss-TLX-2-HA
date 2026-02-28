# CLAUDE.md — AI Assistant Guide for Danfoss-TLX-2-HA

This document describes the codebase structure, conventions, and development workflows for AI assistants working in this repository.

---

## Project Overview

**Danfoss-TLX-2-HA** is a Python-based Home Assistant integration for Danfoss TLX Pro solar inverters. It communicates with the inverter via the proprietary **EtherLynx UDP protocol** (port 48004) and bridges inverter data to Home Assistant using either MQTT auto-discovery or command-line sensors.

**License**: MIT
**Language**: Python 3.9+
**Documentation language**: German (comments, README, docstrings)

---

## Repository Structure

```
Danfoss-TLX-2-HA/
├── danfoss_etherlynx.py        # Core UDP protocol library (38KB)
├── danfoss_ha_bridge.py        # Home Assistant bridge daemon (14KB)
├── danfoss_config.yaml         # User configuration template
├── configuration.yaml          # Home Assistant sensor/automation examples
├── danfoss_etherlynx.service   # systemd service unit file
├── README.md                   # User documentation (German)
├── LICENSE                     # MIT License
├── .gitignore                  # Standard Python gitignore
└── ComLynx and EtherLynx User Guide.pdf  # Official Danfoss protocol spec
```

No build system, test framework, or CI/CD pipeline is present. The project is deployed as plain Python scripts.

---

## Key Files

### `danfoss_etherlynx.py`
The low-level protocol library. Everything needed to speak EtherLynx lives here.

**Key components:**
- `MessageID` enum — Packet type identifiers: `PING` (0x01), `GET_SET_PARAMETER` (0x02), `GET_SET_TEXT` (0x03)
- `Flag` class — Bitmask constants for the protocol header flags field
- `DataType` enum — 12 numeric data type variants (BOOLEAN, SIGNED32, UNSIGNED32, FLOAT, etc.)
- `ParameterDef` dataclass — Descriptor for each inverter parameter: Danfoss parameter ID, unit, scale factor, HA `device_class`
- `TLX_PARAMETERS` dict — Registry of ~40 readable inverter parameters keyed by a snake_case name (e.g. `grid_power_total`, `pv_voltage_1`)
- `DanfossEtherLynx` class — Main client; wraps a UDP socket, implements `ping()`, `get_parameters()`, `get_text()`, `discover_serial()`
- Module-level helpers: `build_ping_packet()`, `build_get_parameters_packet()`, `parse_ping_response()`, `parse_parameter_response()`

**Protocol notes:**
- Packets are little-endian (Intel byte order)
- Fixed 52-byte header followed by variable payload
- Parameter requests can be batched (multiple IDs in one packet)
- Serial number must be included in the header after discovery

### `danfoss_ha_bridge.py`
The HA integration layer. Reads from `danfoss_etherlynx.py` and publishes to Home Assistant.

**Key components:**
- `BridgeConfig` dataclass — Holds all runtime configuration
- `load_config(path, args)` — Loads YAML → applies environment variable overrides → applies CLI argument overrides
- `publish_mqtt_discovery()` — Generates HA MQTT discovery payloads for each sensor
- `publish_values()` — Reads current inverter values and publishes to MQTT
- `run_mqtt_daemon()` — Main loop; polls at three different intervals (realtime, energy, system)
- `run_json_mode()` — Single-shot execution returning JSON; used with HA `command_line` sensors

**Two operation modes** (select via `--mode`):
1. `mqtt` — Long-running daemon with periodic polling and MQTT publishing
2. `json` — One-shot JSON output to stdout, suitable for HA command_line platform

### `danfoss_config.yaml`
Configuration template. Copy and fill in before running.

```yaml
inverter_ip: "192.168.1.100"
inverter_serial: ""                  # auto-detected if empty
pv_strings: 2                        # 2 or 3 depending on model

mqtt_host: "localhost"
mqtt_port: 1883
mqtt_user: ""
mqtt_password: ""
mqtt_topic_prefix: "danfoss_tlx"
mqtt_discovery_prefix: "homeassistant"

poll_interval_realtime: 15           # power, voltage, current (seconds)
poll_interval_energy: 300            # energy counters (seconds)
poll_interval_system: 3600           # firmware/model info (seconds)

log_level: "INFO"
```

### `configuration.yaml`
Ready-to-use Home Assistant configuration snippets:
- MQTT-based sensors (auto-discovery preferred)
- `command_line` sensor fallback
- ~20 template sensors with Jinja2 expressions (efficiency calculation, totals, etc.)
- Automations: error alerts, daily production reports, high-output notifications
- Energy Dashboard integration

### `danfoss_etherlynx.service`
systemd unit file for the MQTT daemon:
- Runs as user `homeassistant`
- Depends on `network-online.target` and `mosquitto.service`
- Restarts on failure (30 s delay, max 5 restarts in 300 s)
- Sets MQTT status to `offline` via `ExecStop`

---

## Code Conventions

### Language
All comments, docstrings, variable descriptions, and user-facing messages are written in **German**. Keep this convention when adding new code.

### Naming
| Construct | Convention | Example |
|---|---|---|
| Functions / variables | `snake_case` | `grid_power_total` |
| Classes | `PascalCase` | `DanfossEtherLynx`, `ParameterDef` |
| Constants | `UPPER_SNAKE_CASE` | `ETHERLYNX_PORT`, `MODULE_COMM_BOARD` |
| Private methods | leading `_` | `_pad_serial()`, `_build_header()` |

### Type Hints
Use Python stdlib type hints throughout: `Optional`, `Dict`, `List`, `Any`, `Tuple`. Do not add third-party typing libraries.

### Dataclasses
Prefer `@dataclass` for structured configuration and parameter definitions. See `ParameterDef` and `BridgeConfig` as reference.

### Enums
Use `enum.Enum` or `enum.IntEnum` for fixed value sets. See `MessageID`, `Flag`, `DataType`.

### Error Handling
- Log errors with the `logging` module; do not print to stdout (except in json mode)
- Use `logger.exception()` for unexpected exceptions
- Tolerate missing parameters gracefully — return `None` rather than raising
- Socket operations must have explicit timeouts
- Mark inverter offline after 10 consecutive failed reads (see `run_mqtt_daemon`)

### Protocol Accuracy
- All byte layouts must match the official Danfoss EtherLynx spec (see the included PDF)
- Include chapter/section citations in comments when referencing the spec
- Little-endian byte order for all multi-byte fields (`struct.pack("<...")`)
- Use exact Danfoss parameter IDs and module IDs from the spec

---

## Configuration Layering

Configuration is resolved in priority order (highest wins):

1. **CLI arguments** (`--inverter-ip`, `--mqtt-host`, etc.)
2. **Environment variables** (e.g. `DANFOSS_INVERTER_IP`, `DANFOSS_MQTT_HOST`)
3. **YAML file** (`danfoss_config.yaml`)
4. **Hardcoded defaults** (in `BridgeConfig`)

When modifying config handling, maintain this layering in `load_config()`.

---

## Running the Integration

### Quick test (discover inverter)
```bash
python3 danfoss_etherlynx.py 192.168.1.100 --mode discover
```

### Read all parameters as JSON
```bash
python3 danfoss_etherlynx.py 192.168.1.100 --mode all -v
```

### Run MQTT daemon
```bash
python3 danfoss_ha_bridge.py --mode mqtt --config danfoss_config.yaml
```

### Run as systemd service
```bash
sudo cp danfoss_etherlynx.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now danfoss_etherlynx
sudo journalctl -u danfoss_etherlynx -f
```

---

## Dependencies

### Required (stdlib only, no install needed for core library)
- `socket`, `struct`, `logging`, `json`, `time`, `pathlib`, `dataclasses`, `enum`

### Optional (install as needed)
```bash
pip install paho-mqtt   # for MQTT daemon mode
pip install PyYAML      # for YAML config file support
```

The bridge script imports these lazily and degrades gracefully when absent.

---

## TLX_PARAMETERS Registry

Each entry in `TLX_PARAMETERS` (in `danfoss_etherlynx.py`) is a `ParameterDef` with:
- `param_id` — Danfoss parameter number (from spec)
- `module_id` — Which board/module to query
- `data_type` — `DataType` enum value
- `scale` — Divide raw integer by this value to get engineering units
- `unit` — Display unit string (e.g. `"W"`, `"V"`, `"kWh"`)
- `device_class` — Home Assistant device class string for MQTT discovery
- `description` — German description string

When adding new parameters, follow this pattern exactly and include the Danfoss parameter ID reference in a comment.

---

## Adding New Sensors

1. Add a new `ParameterDef` entry to `TLX_PARAMETERS` in `danfoss_etherlynx.py`
2. Verify the parameter ID, module ID, data type, and scaling factor against the PDF spec
3. Add a corresponding entry to `configuration.yaml` if a template sensor or automation is needed
4. Test with `--mode all` to confirm the raw value reads correctly

---

## Development Notes

- No formal test suite exists. Manual testing against a live inverter (or captured UDP packets) is the current approach.
- No CI/CD pipeline is configured.
- The project is intentionally kept dependency-light — avoid adding third-party packages unless essential.
- The README is the primary user documentation and is written in German; keep it in sync with any behavioral changes.
- The included PDF (`ComLynx and EtherLynx User Guide.pdf`) is the authoritative reference for all protocol details. Consult it before modifying packet structure.

---

## Git Workflow

- Primary remote branch: `origin/main`
- Feature/AI branches follow the pattern: `claude/<description>-<id>`
- Commit messages should be concise and in English (the git history uses English)
- There are no protected branch rules or required CI checks currently
