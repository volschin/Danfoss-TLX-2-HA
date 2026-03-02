# CLAUDE.md — AI Assistant Guide for Danfoss-TLX-2-HA

This document describes the codebase structure, conventions, and development workflows for AI assistants working in this repository.

---

## Project Overview

**Danfoss-TLX-2-HA** is a Python-based Home Assistant integration for Danfoss TLX Pro solar inverters. It communicates with the inverter via the proprietary **EtherLynx UDP protocol** (port 48004) and exposes inverter data as native HA sensor entities via a HACS-compatible custom component.

**License**: MIT
**Language**: Python 3.11+
**Documentation language**: German (comments, README, docstrings)
**HACS**: Yes — install via Home Assistant Community Store

---

## Repository Structure

```
Danfoss-TLX-2-HA/
├── hacs.json                        # HACS metadata (name, render_readme)
├── pyproject.toml                   # pytest/ruff configuration
├── custom_components/
│   └── danfoss_tlx/                 # HA custom component (HACS install target)
│       ├── __init__.py              # Integration setup / entry point
│       ├── manifest.json            # HA integration metadata (keys: domain, name, then alphabetical)
│       ├── const.py                 # Shared constants (DOMAIN, CONF_* keys)
│       ├── config_flow.py           # UI config flow + options flow
│       ├── coordinator.py           # DataUpdateCoordinator (polls inverter)
│       ├── sensor.py                # SensorEntity subclasses
│       ├── strings.json             # German UI strings
│       ├── etherlynx.py             # EtherLynx protocol library (copied from root)
│       ├── brand/
│       │   ├── icon.png             # HACS brand icon (256×256)
│       │   └── logo.png             # HACS brand logo (256×256)
│       └── translations/
│           └── en.json              # English UI translations
├── tests/                           # pytest test suite (~98 tests, 88% coverage)
│   ├── __init__.py
│   ├── conftest.py                  # Shared fixtures (mock_hass, mock_config_entry, etc.)
│   ├── test_etherlynx.py            # Protocol library tests (~53 tests)
│   ├── test_coordinator.py          # Coordinator tests (~7 tests)
│   ├── test_sensor.py               # Sensor entity tests (~13 tests)
│   ├── test_config_flow.py          # Config flow tests (~7 tests)
│   ├── test_init.py                 # Integration setup tests (~3 tests)
│   └── test_e2e_inverter.py         # E2E tests against real inverter (requires INVERTER_IP env var)
├── .github/
│   ├── release-drafter.yml          # Release notes template + version resolver
│   └── workflows/
│       ├── test.yml                 # Test & Lint (Python 3.11–3.13, ruff, pytest)
│       ├── hacs.yml                 # HACS Validation
│       ├── hassfest.yml             # Hassfest Validation
│       └── release.yml              # Release Drafter (auto-drafts releases from PRs)
├── danfoss_etherlynx.py             # Standalone protocol library (also used as etherlynx.py)
├── danfoss_ha_bridge.py             # Legacy MQTT bridge daemon (kept for reference)
├── danfoss_config.yaml              # Legacy MQTT bridge configuration template
├── configuration.yaml               # HA sensor/automation examples (legacy)
├── danfoss_etherlynx.service        # systemd service unit (legacy MQTT daemon)
├── README.md                        # User documentation (German)
├── CLAUDE.md                        # This file
├── LICENSE                          # MIT License
├── .gitignore                       # Standard Python gitignore
└── ComLynx and EtherLynx User Guide.pdf  # Official Danfoss protocol spec
```

**Primary integration path**: HACS installs `custom_components/danfoss_tlx/` into Home Assistant.
**Legacy path**: The MQTT bridge (`danfoss_ha_bridge.py` + systemd service) remains for users who cannot use HACS.

---

## Key Files

### HACS Custom Component (`custom_components/danfoss_tlx/`)

#### `__init__.py`
Integration entry point. Calls `async_setup_entry` and `async_unload_entry`. Registers the `sensor` platform and sets up a listener to reload when options change.

#### `manifest.json`
HA integration manifest. Required fields: `domain`, `name`, `version`, `iot_class`, `config_flow`, `codeowners`, `documentation`, `issue_tracker`. No external `requirements` — the protocol library is stdlib-only. **Important**: keys must be ordered as `domain`, `name`, then remaining keys alphabetically (enforced by hassfest).

#### `const.py`
All shared constants: `DOMAIN = "danfoss_tlx"`, `CONF_*` config keys, default values.

#### `config_flow.py`
- `DanfossConfigFlow` — user-facing setup: collects inverter IP, optional serial, PV string count, poll interval; verifies connectivity via a background thread call to `DanfossEtherLynx.discover()`
- `DanfossOptionsFlow` — edit poll interval and PV string count post-setup

#### `coordinator.py`
`DanfossCoordinator(DataUpdateCoordinator)` — polls the inverter on a configurable interval. Runs `DanfossEtherLynx.read_all()` in an executor thread. Handles auto-discovery of serial on first connect, resets the client on consecutive failures so the next poll retriggers discovery.

#### `sensor.py`
- `DanfossSensor` — one per entry in `TLX_PARAMETERS`; omits PV string 3 sensors when `pv_strings == 2`
- `DanfossOperationModeSensor` — maps numeric `operation_mode` to a human-readable German text via `OPERATION_MODES`
- All sensors share a single HA device entry keyed by `(DOMAIN, entry.entry_id)`

#### `etherlynx.py`
Verbatim copy of `danfoss_etherlynx.py` kept inside the component package so HACS installs a self-contained directory. Any changes to the protocol library must be mirrored in both files.

#### `strings.json` / `translations/en.json`
UI strings for the config flow and options flow. `strings.json` is German (primary); `translations/en.json` is English for the HA translation system.

---

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
- Use exact Danfoss parameter IDs and module IDs from the spec
- See "Protocol Byte Order" below for correct endianness per field

### Protocol Byte Order

The EtherLynx protocol uses **mixed endianness** — not uniformly little-endian:

| Field | Byte Order | Notes |
|-------|-----------|-------|
| Header `data_offset` | Raw byte (0x0D) | Not bit-shifted, single byte |
| Header `data_length`, `sequence`, `ack` | Big-Endian | `struct.pack(">H", ...)` |
| Payload `num_params` (request) | Little-Endian | `struct.pack("<H", ...)` |
| Response `num_params` | First byte of 4-byte header | Single byte, not a 16-bit field |
| Parameter values | Big-Endian, right-aligned | In 4-byte field, `struct.unpack(">I", ...)` then apply data type |

### Known Sentinel Values

- **Temperature 127°C** — No physical sensor connected; should be treated as "unavailable"

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
2. Mirror the identical change in `custom_components/danfoss_tlx/etherlynx.py`
3. Verify the parameter ID, module ID, data type, and scaling factor against the PDF spec
4. Test with `python3 danfoss_etherlynx.py <ip> --mode all` to confirm the raw value reads correctly
5. The HACS sensor platform picks it up automatically — no changes to `sensor.py` needed

---

## Installing via HACS

1. In HACS → Integrations → ⋮ → Custom repositories → add this repo URL, category: Integration
2. Install "Danfoss TLX Pro"
3. Restart Home Assistant
4. Settings → Devices & Services → Add Integration → search "Danfoss TLX Pro"
5. Enter inverter IP, optionally serial, PV string count, poll interval

---

## Testing

The project has a pytest-based test suite with ~98 tests and 88% code coverage.

### Running tests
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install pytest pytest-asyncio pytest-cov homeassistant voluptuous
pytest -v
pytest --cov=custom_components.danfoss_tlx --cov-report=term-missing
```

### Test structure
- **`tests/conftest.py`** — Shared fixtures: `mock_hass`, `mock_config_entry`, `sample_inverter_data`, `make_ping_response`, `make_parameter_response`
- **`tests/test_etherlynx.py`** — Protocol library: packet building/parsing, socket mocking, registry validation
- **`tests/test_coordinator.py`** — DataUpdateCoordinator: discovery, serial handling, error recovery
- **`tests/test_sensor.py`** — Sensor entities: value mapping, PV string filtering, device info
- **`tests/test_config_flow.py`** — Config/options flows: form rendering, connection testing
- **`tests/test_init.py`** — Integration setup/unload, platform forwarding
- **`tests/test_e2e_inverter.py`** — End-to-end tests against a real inverter; skipped unless `INVERTER_IP` env var is set. Run with: `INVERTER_IP=x.x.x.x pytest tests/test_e2e_inverter.py -v -s`

### Writing tests
- Mock `socket.socket` for protocol tests — never open real UDP sockets
- Patch `DataUpdateCoordinator.__init__` with `return_value=None` in coordinator tests (avoids HA frame context requirement)
- Use fixtures from `conftest.py` for consistent test data
- The CI enforces `--cov-fail-under=85`

---

## CI/CD

Four GitHub Actions workflows run on pushes to `main` and on pull requests:

| Workflow | File | Purpose |
|---|---|---|
| **Test & Lint** | `.github/workflows/test.yml` | Runs ruff linter, verifies etherlynx copies are in sync, runs pytest (Python 3.11–3.13) |
| **HACS Validation** | `.github/workflows/hacs.yml` | Validates HACS integration requirements (brand assets, manifest, etc.) |
| **Hassfest** | `.github/workflows/hassfest.yml` | Validates HA integration manifest (key ordering, required fields) |
| **Release Drafter** | `.github/workflows/release.yml` | Auto-drafts release notes from merged PRs (push to main only) |

### Release Drafter labels
PR labels control version bumping and changelog categories:
- `feature` / `enhancement` → "New Features" section, minor version bump
- `fix` / `bug` → "Bug Fixes" section, patch version bump
- `chore` / `ci` / `refactor` → "Maintenance" section
- `major` → major version bump

---

## Development Notes

- The project is intentionally kept dependency-light — avoid adding third-party packages unless essential.
- The README is the primary user documentation and is written in German; keep it in sync with any behavioral changes.
- The included PDF (`ComLynx and EtherLynx User Guide.pdf`) is the authoritative reference for all protocol details. Consult it before modifying packet structure.
- Both copies of etherlynx.py must stay in sync — CI verifies this with a diff check.
- Run `ruff check` before committing; CI enforces clean linting.

---

## Git Workflow

- Primary remote branch: `origin/main`
- Feature/AI branches follow the pattern: `claude/<description>-<id>`
- Commit messages should be concise and in English (the git history uses English)
- CI checks (test, lint, HACS, hassfest) run on all pushes and PRs to main
