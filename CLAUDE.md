# CLAUDE.md — AI Assistant Guide for Danfoss-TLX-2-HA

This document describes the codebase structure, conventions, and development workflows for AI assistants working in this repository.

---

## Project Overview

**Danfoss-TLX-2-HA** is a Python-based Home Assistant integration for Danfoss TLX Pro solar inverters. It communicates with the inverter via the proprietary **EtherLynx UDP protocol** (port 48004) and exposes inverter data as native HA sensor entities via a HACS-compatible custom component.

**License**: MIT
**Language**: Python 3.11+
**Documentation language**: German (comments, README, docstrings)
**HACS**: Yes — install via Home Assistant Community Store
**Quality Scale**: Platinum

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
│       ├── diagnostics.py           # Diagnostics platform (config entry diagnostics)
│       ├── strings.json             # German UI strings (config, exceptions, entities)
│       ├── icons.json               # MDI icon translations for all sensor entities
│       ├── quality_scale.yaml       # HA Quality Scale Gold declaration
│       ├── etherlynx.py             # EtherLynx protocol library
│       ├── py.typed                 # PEP 561 type marker (Platinum requirement)
│       ├── brand/
│       │   ├── icon.png             # HACS brand icon (256×256)
│       │   └── logo.png             # HACS brand logo (256×256)
│       └── translations/
│           └── en.json              # English UI translations (config, exceptions, entities)
├── dashboards/
│   └── danfoss-tlx-inverter.yaml    # Example Home Assistant dashboard
├── tests/                           # pytest test suite (~169 tests, 95% coverage)
│   ├── __init__.py
│   ├── conftest.py                  # Shared fixtures (mock_hass, mock_config_entry, etc.)
│   ├── test_etherlynx.py            # Protocol library tests (~58 tests)
│   ├── test_coordinator.py          # Coordinator tests (~10 tests)
│   ├── test_sensor.py               # Sensor entity tests (~34 tests)
│   ├── test_config_flow.py          # Config flow tests (~14 tests)
│   ├── test_diagnostics.py          # Diagnostics platform tests (~9 tests)
│   ├── test_init.py                 # Integration setup tests (~3 tests)
│   └── test_e2e_inverter.py         # E2E tests against real inverter (requires INVERTER_IP env var)
├── .github/
│   ├── release-drafter.yml          # Release notes template + version resolver
│   └── workflows/
│       ├── test.yml                 # Test & Lint (Python 3.11–3.13, ruff, pytest)
│       ├── hacs.yml                 # HACS Validation
│       ├── hassfest.yml             # Hassfest Validation
│       └── release.yml              # Release Drafter (auto-drafts releases from PRs)
├── README.md                        # User documentation (German)
├── CLAUDE.md                        # This file
├── LICENSE                          # MIT License
├── .gitignore                       # Standard Python gitignore
└── ComLynx and EtherLynx User Guide.pdf  # Official Danfoss protocol spec
```

**Primary integration path**: HACS installs `custom_components/danfoss_tlx/` into Home Assistant.

---

## Key Files

### HACS Custom Component (`custom_components/danfoss_tlx/`)

#### `__init__.py`
Integration entry point. Calls `async_setup_entry` and `async_unload_entry`. Registers the `sensor` platform and sets up a listener to reload when options change.

#### `manifest.json`
HA integration manifest. Required fields: `domain`, `name`, `version`, `iot_class`, `config_flow`, `codeowners`, `documentation`, `issue_tracker`. Includes `quality_scale: "platinum"` and `single_config_entry: false`. No external `requirements` — the protocol library is stdlib-only. **Important**: keys must be ordered as `domain`, `name`, then remaining keys alphabetically (enforced by hassfest).

#### `const.py`
All shared constants: `DOMAIN = "danfoss_tlx"`, `CONF_*` config keys, default values.

#### `config_flow.py`
- `DanfossConfigFlow` — user-facing setup: collects inverter IP, optional serial, PV string count, poll interval; verifies connectivity via a background thread call to `DanfossEtherLynx.discover()`
- `DanfossOptionsFlow` — edit poll interval and PV string count post-setup

#### `coordinator.py`
`DanfossCoordinator(DataUpdateCoordinator)` — polls the inverter on a configurable interval. Calls `DanfossEtherLynx.read_all()` natively async (no executor thread). Handles auto-discovery of serial on first connect, resets the client on consecutive failures so the next poll retriggers discovery. Logs WARNING on first failure and INFO on recovery (log-when-unavailable). Uses `HomeAssistantError` with translation keys for setup exceptions; `UpdateFailed` with a plain string for poll errors.

#### `sensor.py`
- `DanfossSensor` — one per entry in `TLX_PARAMETERS`; omits PV string 3 sensors when `pv_strings == 2`
- `DanfossOperationModeSensor` — maps numeric `operation_mode` to a human-readable text
- `DanfossEventSensor` — maps numeric `latest_event` to a human-readable text
- All sensors use `_attr_translation_key` for entity translations (Gold requirement). Icons come from `icons.json`.
- All sensors share a single HA device entry keyed by `(DOMAIN, entry.entry_id)`

#### `diagnostics.py`
Diagnostics platform for the Platinum quality scale. Returns config data (serial redacted), coordinator state, and latest inverter readings via `async_get_config_entry_diagnostics`.

#### `quality_scale.yaml`
Platinum quality scale declaration. Declares compliance with all Bronze, Silver, Gold, and Platinum rules. Rules that don't apply (discovery, reauthentication, actions, stale-devices, inject-websession) are marked as `exempt` with German comments.

#### `etherlynx.py`
The EtherLynx protocol library. Self-contained inside the component package so HACS installs everything in one directory.

**Key components:**
- `MessageID` enum — Packet type identifiers: `PING` (0x01), `GET_SET_PARAMETER` (0x02), `GET_SET_TEXT` (0x03)
- `Flag` class — Bitmask constants for the protocol header flags field
- `DataType` enum — 12 numeric data type variants (BOOLEAN, SIGNED32, UNSIGNED32, FLOAT, etc.)
- `ParameterDef` dataclass — Descriptor for each inverter parameter: Danfoss parameter ID, unit, scale factor, HA `device_class`
- `TLX_PARAMETERS` dict — Registry of ~50 readable inverter parameters keyed by a snake_case name (e.g. `grid_power_total`, `pv_voltage_1`)
- `_EtherLynxProtocol` class — asyncio `DatagramProtocol` for non-blocking UDP communication; matches requests to responses via a `Future`
- `DanfossEtherLynx` class — Async main client; uses `_EtherLynxProtocol` via `create_datagram_endpoint`; all public methods are `async def`
- Module-level helpers: `build_ping_packet()`, `build_get_parameters_packet()`, `parse_ping_response()`, `parse_parameter_response()`

**Protocol notes:**
- Fixed 52-byte header followed by variable payload
- Parameter requests can be batched (multiple IDs in one packet)
- Serial number must be included in the header after discovery

#### `strings.json` / `translations/en.json`
UI strings organized in three sections: `config` (config flow), `options` (options flow), `exceptions` (translated error messages), `entity` (sensor name translations for all 52 entities). `strings.json` is German (primary); `translations/en.json` is English.

#### `icons.json`
MDI icon definitions for all 52 sensor entities under `entity.sensor.<key>.default`. Icons are grouped by category (energy, voltage, current, power, frequency, temperature, status).

---

## Code Conventions

### Language
All comments, docstrings, variable descriptions, and user-facing messages are written in **German**. Keep this convention when adding new code.

GitHub release notes are written in **English**.

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
Prefer `@dataclass` for structured configuration and parameter definitions. See `ParameterDef` as reference.

### Enums
Use `enum.Enum` or `enum.IntEnum` for fixed value sets. See `MessageID`, `Flag`, `DataType`.

### Error Handling
- Log errors with the `logging` module; do not print to stdout (except in json mode)
- Use `logger.exception()` for unexpected exceptions
- Tolerate missing parameters gracefully — return `None` rather than raising
- Socket operations must have explicit timeouts
- Mark inverter offline after consecutive failed reads

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

## Dependencies

All dependencies are stdlib-only — no install needed for the core library:
- `socket`, `struct`, `logging`, `json`, `time`, `pathlib`, `dataclasses`, `enum`

---

## TLX_PARAMETERS Registry

Each entry in `TLX_PARAMETERS` (in `custom_components/danfoss_tlx/etherlynx.py`) is a `ParameterDef` with:
- `param_id` — Danfoss parameter number (from spec)
- `module_id` — Which board/module to query
- `data_type` — `DataType` enum value
- `scale` — Divide raw integer by this value to get engineering units
- `unit` — Display unit string (e.g. `"W"`, `"V"`, `"kWh"`)
- `device_class` — Home Assistant device class string (e.g. `"power"`, `"energy"`, `"voltage"`)
- `description` — German description string

When adding new parameters, follow this pattern exactly and include the Danfoss parameter ID reference in a comment.

---

## Adding New Sensors

1. Add a new `ParameterDef` entry to `TLX_PARAMETERS` in `custom_components/danfoss_tlx/etherlynx.py`
2. Verify the parameter ID, module ID, data type, and scaling factor against the PDF spec
3. Add the sensor's translation key to `strings.json` (`entity.sensor.<key>.name`) and `translations/en.json`
4. Add the sensor's icon to `icons.json` (`entity.sensor.<key>.default`)
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

The project has a pytest-based test suite with ~169 tests and 95% code coverage.

### Running tests
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install pytest pytest-asyncio pytest-cov homeassistant voluptuous
pytest -v
pytest --cov=custom_components.danfoss_tlx --cov-report=term-missing
```

### Test structure
- **`tests/conftest.py`** — Shared fixtures: `mock_hass`, `mock_config_entry`, `sample_inverter_data`, `make_ping_response`, `make_parameter_response`, `_make_mock_client` (async context manager helper)
- **`tests/test_etherlynx.py`** — Protocol library: packet building/parsing, socket mocking, registry validation (~87 tests)
- **`tests/test_coordinator.py`** — DataUpdateCoordinator: discovery, serial handling, error recovery (~14 tests)
- **`tests/test_sensor.py`** — Sensor entities: value mapping, PV string filtering, device info (~34 tests)
- **`tests/test_config_flow.py`** — Config/options flows: form rendering, connection testing, error handling (~19 tests)
- **`tests/test_diagnostics.py`** — Diagnostics: config entry diagnostics, serial redaction, null data handling (~9 tests)
- **`tests/test_init.py`** — Integration setup/unload, platform forwarding (~6 tests)
- **`tests/test_e2e_inverter.py`** — End-to-end tests against a real inverter; skipped unless `INVERTER_IP` env var is set. Run with: `INVERTER_IP=x.x.x.x pytest tests/test_e2e_inverter.py -v -s`

### Writing tests
- Mock `socket.socket` for protocol tests — never open real UDP sockets
- Patch `DataUpdateCoordinator.__init__` with `return_value=None` in coordinator tests (avoids HA frame context requirement)
- Use fixtures from `conftest.py` for consistent test data
- The CI enforces `--cov-fail-under=95`

---

## CI/CD

Four GitHub Actions workflows run on pushes to `main` and on pull requests:

| Workflow | File | Purpose |
|---|---|---|
| **Test & Lint** | `.github/workflows/test.yml` | Runs ruff linter and pytest (Python 3.11–3.13) |
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
- Run `ruff check` before committing; CI enforces clean linting.
- **Update `CLAUDE.md` at the end of every change** — keep file paths, test counts, version-sensitive descriptions, and conventions in sync with the actual code.

---

## Git Workflow

- Primary remote branch: `origin/main`
- Feature/AI branches follow the pattern: `claude/<description>-<id>`
- Commit messages should be concise and in English (the git history uses English)
- CI checks (test, lint, HACS, hassfest) run on all pushes and PRs to main

### Release Governance

**Never publish a GitHub release until all four CI workflows pass green on `main`:**

1. Check `gh run list --limit 8` after pushing to main
2. Confirm all four workflows — **Test & Lint**, **HACS Validation**, **Hassfest**, **Release Drafter** — show `completed / success`
3. Only then bump `manifest.json` version and publish the release

If any workflow fails, fix it first, push the fix, and wait for a clean run before releasing.
