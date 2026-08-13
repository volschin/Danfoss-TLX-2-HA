# Danfoss-TLX-2-HA repository notes

HACS Home Assistant integration for Danfoss TLX Pro inverters. The stdlib-only
EtherLynx client communicates asynchronously over UDP port 48004; the integration
lives in `custom_components/danfoss_tlx/`.

## Commands

```bash
ruff check custom_components tests
pytest -v
pytest --cov=custom_components.danfoss_tlx --cov-report=term-missing
INVERTER_IP=x.x.x.x pytest tests/test_e2e_inverter.py -v -s
```

CI also runs HACS and hassfest validation. The coverage gate is 95%. Never claim
live protocol validation from mocked tests; the E2E suite requires a real
inverter and is skipped without `INVERTER_IP`.

## Protocol invariants

- `docs/ComLynx and EtherLynx User Guide.pdf` is authoritative. Verify packet changes
  against it and cite the relevant section in protocol comments.
- EtherLynx uses mixed byte order: header length/sequence/ack are big-endian;
  request `num_params` is little-endian; response count is a single byte;
  parameter values are big-endian and right-aligned.
- Correlate replies by transaction number, message ID and response flag. Also
  verify each returned parameter's echoed index/subindex.
- A failed parameter batch retries once and then fails the poll; never report a
  partial batch as a successful update.
- `127 C` is the no-sensor sentinel and must become unavailable.
- Socket operations need explicit timeouts and UDP endpoints must be closed on
  unload/reload.

## Home Assistant contract

- Keep code comments, docstrings, primary UI strings and README in German;
  `translations/en.json`, commit messages and release notes are English.
- Adding a sensor requires matching entries in `TLX_PARAMETERS`, `strings.json`,
  `translations/en.json` and `icons.json`.
- Preserve manifest key ordering (`domain`, `name`, then alphabetical) and keep
  `quality_scale.yaml` truthful when behavior changes.
- Redact the serial number from diagnostics.
- The core protocol library remains dependency-free; add dependencies only when
  the current requirement cannot be met with stdlib/Home Assistant APIs.

Follow YAGNI. Do not add unused knobs, helpers or APIs; protocol enums/constants
may remain exhaustive because they document the wire format.
