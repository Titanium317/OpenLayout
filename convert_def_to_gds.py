#!/usr/bin/env python3
"""Convert an OpenROAD DEF into a stream GDS with the ORFS KLayout tool.

The OpenROAD binary shipped in the current container does not expose
``write_gds``.  ORFS already provides a KLayout based DEF-to-stream
converter, so this small wrapper keeps the conversion reproducible and
records the result next to the flow artifacts.

The LEF list matters: ``def2stream.py`` reads LEFs through the KLayout *tech
file*, not through ``in_files``.  Passing the stock platform ``*.lyt`` leaves
its ``<lef-files>`` pointing at a path that does not exist, every standard cell
becomes an empty dummy macro, and the resulting GDS is not the routed layout --
which silently invalidates any DRC/LVS number produced from it.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path("/data/taiyuzhou")
CONTAINER = "docker.io/openroad/orfs:latest"
CONTAINER_ROOT = "/OpenROAD-flow-scripts/flow/util/def2stream.py"


def _container_path(path: Path) -> str:
    """Return a path visible through the /data/taiyuzhou bind mount."""
    p = path.resolve()
    try:
        return "/data/taiyuzhou/" + str(p.relative_to(ROOT))
    except ValueError as exc:
        raise SystemExit(f"path must be under {ROOT}: {p}") from exc


def resolve_tech_file(template: Path, lefs: list[Path], out_dir: Path,
                      design: str) -> tuple[Path, bool]:
    """Return a tech file whose ``<lef-files>`` list actually exists.

    The stock platform ``*.lyt`` files point at LEFs by a path relative to the
    platform directory (e.g. ``./NangateOpenCellLibrary.mod.lef``) that does not
    resolve when KLayout runs from anywhere else.  Without those LEFs the DEF
    reader turns every standard cell into an empty *dummy macro*, so the
    streamed GDS is not the routed layout and the signoff DRC is meaningless
    (measured: 6662 violations instead of 96 on nangate45/gcd).

    ORFS avoids this by generating a per-design ``klayout.lyt``; this function
    does the same thing locally: rewrite every ``<lef-files>`` entry to the
    absolute paths we were given.  When no LEF list is supplied the template is
    used unchanged (and reported as unresolved).
    """
    if not lefs:
        return template, False
    text = template.read_text()
    entries = "".join(
        "<lef-files>%s</lef-files>" % _container_path(p) for p in lefs)
    if "<lef-files>" in text:
        text = re.sub(r"(<lef-files>.*?</lef-files>\s*)+", entries, text,
                      count=1)
    elif "</lefdef>" in text:
        text = text.replace("</lefdef>", entries + "\n  </lefdef>", 1)
    else:
        return template, False

    # A relative <map-file> (e.g. ihp's ``sg13g2.map``) is resolved against the
    # tech file's own directory, so moving the tech file breaks it.  Make it
    # absolute while we are rewriting references anyway.
    def _abs_map(m: "re.Match[str]") -> str:
        name = m.group(1).strip()
        if not name or name.startswith("/") or "(" in name:
            return m.group(0)
        target = (template.parent / name).resolve()
        return "<map-file>%s</map-file>" % _container_path(target)
    text = re.sub(r"<map-file>([^<]*)</map-file>", _abs_map, text)

    out_dir.mkdir(parents=True, exist_ok=True)
    resolved = out_dir / f"{design}.klayout.lyt"
    resolved.write_text(text)
    return resolved, True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--def", dest="def_file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tech-file", required=True)
    ap.add_argument("--macro-gds", action="append", default=[])
    ap.add_argument("--lef", action="append", default=[],
                    help="LEF file (repeatable) loaded through the tech file; "
                         "without it every macro becomes an empty dummy macro")
    ap.add_argument("--design", required=True)
    ap.add_argument("--seal-file", default="")
    ap.add_argument("--layer-map", default="")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    def_file = Path(args.def_file).resolve()
    out_file = Path(args.out).resolve()
    tech_file = Path(args.tech_file).resolve()
    macros = [Path(p).resolve() for p in args.macro_gds]
    lefs = [Path(p).resolve() for p in args.lef]
    for p in [def_file, tech_file, *macros, *lefs]:
        if not p.exists():
            raise SystemExit(f"missing input: {p}")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    tech_file, lefs_resolved = resolve_tech_file(
        tech_file, lefs, out_file.parent, args.design)
    if not lefs_resolved:
        print("[WARNING] no LEF supplied: macros will be read as empty dummy "
              "macros and the GDS will not match the routed layout",
              file=sys.stderr)

    # The container command is intentionally explicit: this is the same
    # rootless Podman storage used for the validated OpenLayout run.
    cmd = [
        "podman", "--root", "/data/taiyuzhou/containers/storage",
        "--runroot", "/data/taiyuzhou/containers/runroot",
        "--events-backend=file", "--cgroup-manager=cgroupfs", "run", "--rm",
        "--network=none", "--userns=host", "-v", "/data/taiyuzhou:/data/taiyuzhou",
        "-e", "GDS_ALLOW_EMPTY=.*", CONTAINER, "/usr/bin/klayout", "-zz",
        "-rd", f"design_name={args.design}",
        "-rd", f"in_def={_container_path(def_file)}",
        "-rd", f"in_files={' '.join(_container_path(p) for p in macros)}",
        "-rd", f"seal_file={args.seal_file}",
        "-rd", f"out_file={_container_path(out_file)}",
        "-rd", f"tech_file={_container_path(tech_file)}",
        "-rd", f"layer_map={_container_path(Path(args.layer_map).resolve()) if args.layer_map else ''}", "-r", CONTAINER_ROOT,
    ]
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = "/data/taiyuzhou/containers/runtime_openlayout"
    log_path = Path(args.log).resolve() if args.log else out_file.with_suffix(".gds.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as lf:
        lf.write("$ " + " ".join(shlex.quote(x) for x in cmd) + "\n")
        lf.flush()
        proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                              env=env, check=False)
    if proc.returncode != 0 or not out_file.exists() or out_file.stat().st_size == 0:
        raise SystemExit(f"DEF-to-GDS conversion failed (rc={proc.returncode}); see {log_path}")
    log_text = log_path.read_text(errors="ignore")
    dummy_macros = log_text.count("creating dummy macro")
    bad_vias = log_text.count("Invalid via name")
    print(json.dumps({"gds": str(out_file), "bytes": out_file.stat().st_size,
                      "log": str(log_path),
                      "tech_file": str(tech_file),
                      "lefs": [str(p) for p in lefs],
                      "dummy_macros": dummy_macros,
                      "invalid_vias": bad_vias}, indent=2))
    if dummy_macros:
        print(f"[WARNING] {dummy_macros} macros were created empty; the signoff "
              "GDS will not describe the routed layout", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
