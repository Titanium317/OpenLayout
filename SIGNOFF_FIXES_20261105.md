# Signoff fixes — 2026-11-05

The `reports/openlayout_vs_user_agent_43_klayout_comparison_20261103.*` table
reported **DRC clean = 0/43** for OpenLayout. Three defects made that number
meaningless. They are fixed here; the published table must be regenerated with
a fresh run before it is quoted again.

## 1. DEF→GDS conversion never loaded the LEFs (`convert_def_to_gds.py`)

`def2stream.py` reads LEFs through the KLayout **tech file**, not through
`in_files`. The batch runner passed the stock platform `*.lyt`, whose only
`<lef-files>` entry points at `./NangateOpenCellLibrary.mod.lef` — a path that
does not exist. Consequences in `gds/*.gds.log`:

| symptom | designs affected (of 47 logs) |
|---|---|
| `Macro not found in LEF file … creating dummy macro` | 44 |
| `Invalid via name` (up to 592,538 lines) | 38 |
| `DEF UNITS does not match reader DBU` | 32 |

Every standard cell became an empty dummy macro, so the streamed GDS was not the
routed layout.

**Fix**: `--lef` (repeatable) builds a per-design `<design>.klayout.lyt` next to
the GDS with absolute `<lef-files>` entries (and absolutes relative
`<map-file>`), exactly what ORFS does with its generated `klayout.lyt`. The
converter now also reports `dummy_macros` / `invalid_vias` and warns loudly.

## 2. No filler / tap cells were ever inserted (`finish.tcl`, `config.py`)

`filler|tapcell` had zero matches in the whole flow, so every row gap stayed
empty. Measured on `nangate45/gcd`: OpenLayout GDS had **0** FILL/TAP instances
versus **458** for the reference flow.

**Fix**: `finish.tcl` now runs `tapcell` + `filler_placement` (guarded, logged)
before the final DEF/GDS, driven by per-platform `fill_cells` / `tap_cell` /
`tap_distance` defaults and an `insert_fillers` switch.

## 3. 18/43 designs ran the wrong netlist (`openlayout/tops.py`, `fix_top_modules.py`)

`prepare_43_manifest.py` fell back to the *first* `module` line of the
synthesised netlist — a leaf block. 13 designs became `ALU_*_BRENT_KUNG`, plus
`ariane133/136` (an SRAM macro), `tinyRocket` (`CSRFile`),
`i2c-gpio-expander` (`BufferCC_1`).

**Fix**: `openlayout/tops.py` resolves the top authoritative-first —
ORFS `DESIGN_NAME` → RTLIL `\top` attribute → netlist heuristic — and
`fix_top_modules.py` patched the manifest (`top_source` now recorded) and
regenerated `configs/current43/*.yaml`.

## Verification (same DEF, same deck)

`nangate45__gcd__base`, KLayout `FreePDK45.lydrc`:

| stage | violations |
|---|---:|
| as published (no LEF) | 6,662 |
| LEF loaded only | 96 (89 × `WELL.4` from empty rows) |
| LEF + filler insertion | **7** (5 × `METAL2.2`, 2 × `VIA7.4` — real routing) |

`ihp-sg13g2__gcd__base`: 33 → 37. Filler cells are now present, but the
remaining `AFil.*` / `MxFil.*` / `Mx.j/k` hits are **fill-layer density** rules
that need dummy metal fill generation, which this flow does not do yet.

Repro: `net2GDS/tmp_cell/ol_verify2.sh` (LEF fix) and `ol_verify3.sh`,
`ol_verify4.sh` (fill fix). Artifacts under `net2GDS/tmp_cell/ol_verify/`.

## Still open

- Metal/poly dummy fill per platform (closes ihp-sg13g2, gf180, and the
  remaining sky130 density rules).
- Full 43-design re-run (`python run_43_batch.py --force`) and regenerated
  comparison report; the current 0/43 table is superseded.
