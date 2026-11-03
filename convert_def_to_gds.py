#!/usr/bin/env python3
"""Convert an OpenROAD DEF into a stream GDS with the ORFS KLayout tool.

The OpenROAD binary shipped in the current container does not expose
``write_gds``.  ORFS already provides a KLayout based DEF-to-stream
converter, so this small wrapper keeps the conversion reproducible and
records the result next to the flow artifacts.
"""

import argparse
import json
import os
import shlex
import subprocess
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--def", dest="def_file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tech-file", required=True)
    ap.add_argument("--macro-gds", action="append", default=[])
    ap.add_argument("--design", required=True)
    ap.add_argument("--seal-file", default="")
    ap.add_argument("--layer-map", default="")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    def_file = Path(args.def_file).resolve()
    out_file = Path(args.out).resolve()
    tech_file = Path(args.tech_file).resolve()
    macros = [Path(p).resolve() for p in args.macro_gds]
    for p in [def_file, tech_file, *macros]:
        if not p.exists():
            raise SystemExit(f"missing input: {p}")
    out_file.parent.mkdir(parents=True, exist_ok=True)

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
    print(json.dumps({"gds": str(out_file), "bytes": out_file.stat().st_size,
                      "log": str(log_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
