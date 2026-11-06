#!/usr/bin/env python3
"""Run the same KLayout DRC/LVS signoff used by the 43-design baseline.

The OpenLayout flow already emits a routed DEF/ODB and a streamed GDS, but its
original quality report only contained OpenROAD route-DRC and ``not verified``
for LVS.  This adapter evaluates the GDS with the exact deck selected by the
canonical net2GDS signoff record, then writes the result back into each
OpenLayout ``quality_report.json``.

It intentionally never reruns placement or routing.  Use ``--skip-existing``
to leave fresh KLayout reports untouched, or ``--force`` to rerun them.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

ROOT = Path("/data/taiyuzhou")
OL = ROOT / "OpenLayout"
NET2GDS = ROOT / "net2GDS"
MANIFEST = NET2GDS / "reports/openlayout_43_manifest_20261102.json"
BASELINE = NET2GDS / "reports/final_tasks_signoff.json"
IMAGE = os.environ.get("IMAGE", "docker.io/openroad/orfs:latest")
PODMAN = os.environ.get("PODMAN", "podman")
PODMAN_ROOT = os.environ.get("PODMAN_ROOT", str(ROOT / "containers/storage"))
PODMAN_RUNROOT = os.environ.get("PODMAN_RUNROOT", str(ROOT / "containers/runroot"))


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def container_path(path: Path) -> str:
    """Map a host path below /data/taiyuzhou into the signoff container."""
    return "/net2/" + str(path.relative_to(NET2GDS)).replace(os.sep, "/")


def runset_for(sample_id: str, kind: str, baseline: dict) -> Path | None:
    row = baseline.get(sample_id) or {}
    block = row.get("drc" if kind == "drc" else "lvs") or {}
    p = block.get("deck")
    return Path(p) if p else None


def reference_for(sample: dict) -> Path | None:
    """Use the canonical final concat CDL as the LVS reference.

    It contains the post-synthesis top-level netlist plus the platform master
    CDL and is the same reference consumed by the user's Agent signoff.
    """
    task = Path(sample["task_dir"])
    p = task / "work" / "objects" / sample["platform"] / sample["design"] / sample["variant"] / "6_final_concat.cdl"
    return p if p.exists() else None


def parse_drc_count(report: Path) -> int | None:
    if not report.exists():
        return None
    text = report.read_text(errors="replace")
    # A clean run still writes an (empty) <items> section, so keying off
    # <value> made every clean design look "unverified" (0 values -> fallback
    # -> ambiguous).  Count the items themselves.
    if "<items>" in text or "<item>" in text:
        return len(re.findall(r"<item>", text))
    # Some KLayout versions emit a summary report instead of the XML value
    # elements.  Keep this fallback conservative: only a single integer is
    # accepted, otherwise the result is considered unverified.
    nums = re.findall(r"\b\d+\b", text)
    return int(nums[0]) if len(nums) == 1 else None


def lvs_verdict(log: Path, rc: int, report: Path) -> str:
    if rc == 124:
        return "timeout"
    text = log.read_text(errors="replace") if log.exists() else ""
    if "Netlists match" in text:
        return "match"
    if "Netlists don't match" in text or "Netlists do not match" in text:
        return "mismatch"
    if rc != 0 or not report.exists():
        return "not_verified"
    if "RuntimeError" in text or "Netlist::read" in text:
        return "not_verified"
    return "mismatch"


def execute(sample: dict, baseline: dict, force: bool, timeout: int,
            skip_lvs: bool = False) -> dict:
    sid = sample["sample_id"]
    out = OL / "output/current43" / sid
    gds = next(iter(sorted((out / "gds").glob("*.gds"))), None)
    signoff = out / "signoff"
    signoff.mkdir(parents=True, exist_ok=True)
    drc_report = signoff / "klayout_drc.lyrdb"
    drc_log = signoff / "klayout_drc.log"
    lvs_report = signoff / "klayout_lvs.lvsdb"
    lvs_log = signoff / "klayout_lvs.log"
    drc_deck = runset_for(sid, "drc", baseline)
    lvs_deck = runset_for(sid, "lvs", baseline)
    ref = reference_for(sample)
    result = {"sample_id": sid, "platform": sample["platform"], "design": sample["design"]}
    if not gds or not gds.exists():
        result.update({"status": "missing_gds", "drc": {"defined": False}, "lvs": {"defined": False}})
        return result

    def run_target(kind: str, deck: Path | None, report: Path, log: Path, extra: list[str]) -> tuple[int, str]:
        if not deck or not deck.exists():
            return 2, "missing deck"
        # Reuse only a report that is at least as new as the GDS it describes;
        # an older one belongs to a previous (possibly wrong) conversion.
        if report.exists() and not force and report.stat().st_mtime >= gds.stat().st_mtime:
            return 0, "reused"
        cname = "ol_signoff_%s_%s" % (
            re.sub(r"[^A-Za-z0-9_.-]", "_", sid)[:80], kind)
        # A previous timed-out KLayout process may have survived after its
        # podman parent was killed.  Remove only this adapter's own container
        # name before starting a fresh target.
        subprocess.run([PODMAN, "--root", PODMAN_ROOT, "--runroot", PODMAN_RUNROOT,
                        "rm", "-f", cname], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        args = [
            PODMAN, "--root", PODMAN_ROOT, "--runroot", PODMAN_RUNROOT,
            "run", "--rm", "--name", cname,
            "-v", f"{out}:/work",
            "-v", f"{NET2GDS}:/net2",
            IMAGE, "bash", "-lc",
        ]
        if kind == "drc":
            cmd = [
                "klayout", "-zz",
                "-rd", f"in_gds=/work/gds/{gds.name}",
                "-rd", "report_file=/work/signoff/klayout_drc.lyrdb",
                "-r", container_path(deck),
            ]
        else:
            cmd = [
                "klayout", "-b",
                "-rd", f"in_gds=/work/gds/{gds.name}",
                "-rd", f"cdl_file={container_path(ref)}",
                "-rd", f"top_cell={sample['top']}",
                "-rd", "report_file=/work/signoff/klayout_lvs.lvsdb",
                "-r", container_path(deck),
            ]
        shell = " ".join(shlex.quote(x) for x in cmd)
        try:
            with log.open("w") as fh:
                proc = subprocess.run(args + [shell], stdout=fh, stderr=subprocess.STDOUT,
                                      timeout=timeout if timeout else None)
        except subprocess.TimeoutExpired:
            subprocess.run([PODMAN, "--root", PODMAN_ROOT, "--runroot", PODMAN_RUNROOT,
                            "kill", cname], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return 124, "timeout"
        return proc.returncode, "executed"

    # DRC and LVS are run in separate containers so a failed LVS parser cannot
    # suppress a valid DRC report.  A timeout is recorded as 124.
    try:
        drc_rc, drc_action = run_target("drc", drc_deck, drc_report, drc_log, [])
    except subprocess.TimeoutExpired:
        drc_rc, drc_action = 124, "timeout"
    try:
        if skip_lvs:
            lvs_rc, lvs_action = 2, "skipped"
        else:
            lvs_rc, lvs_action = run_target("lvs", lvs_deck, lvs_report, lvs_log, []) if ref else (2, "missing reference CDL")
    except subprocess.TimeoutExpired:
        lvs_rc, lvs_action = 124, "timeout"

    drc_count = parse_drc_count(drc_report)
    drc_status = "clean" if drc_count == 0 else ("violations" if drc_count is not None else ("blocked" if drc_rc != 0 else "not_verified"))
    lvs_status = lvs_verdict(lvs_log, lvs_rc, lvs_report) if ref else "not_verified"
    if skip_lvs:
        lvs_status = "skipped"
    result.update({
        "status": "complete",
        "drc": {"defined": bool(drc_deck and drc_deck.exists()), "engine": "KLayout",
                "deck": str(drc_deck) if drc_deck else None, "report": str(drc_report),
                "log": str(drc_log), "exit_code": drc_rc, "violations": drc_count,
                "status": drc_status, "action": drc_action},
        "lvs": {"defined": bool(lvs_deck and lvs_deck.exists() and ref), "engine": "KLayout",
                "deck": str(lvs_deck) if lvs_deck else None, "reference_cdl": str(ref) if ref else None,
                "report": str(lvs_report), "log": str(lvs_log), "exit_code": lvs_rc,
                "status": lvs_status, "action": lvs_action},
    })
    qpath = out / "quality_report.json"
    q = load(qpath, {}) or {}
    quality = q.get("quality", {}) or {}
    # Preserve the old OpenROAD route result for diagnosis, while making the
    # top-level quality verdict use the same GDS signoff engine as the baseline.
    quality["route_drc_status"] = quality.get("drc")
    quality["route_drc_violations"] = quality.get("drc_violations")
    quality["drc"] = drc_status
    quality["drc_violations"] = drc_count
    quality["drc_engine"] = "KLayout"
    quality["lvs"] = lvs_status
    quality["lvs_engine"] = "KLayout"
    quality["timing_signoff_valid"] = bool(
        quality.get("timing_closed") and quality.get("route_status") == "done" and
        quality.get("finish_status") == "done")
    q["quality"] = quality
    q["signoff"] = {"drc": result["drc"], "lvs": result["lvs"],
                     "acceptance": bool(drc_status == "clean" and lvs_status == "match")}
    qpath.write_text(json.dumps(q, indent=2, ensure_ascii=False) + "\n")
    md = out / "report.md"
    old = md.read_text(errors="replace") if md.exists() else ""
    marker = "## KLayout signoff"
    if marker in old:
        old = old.split(marker, 1)[0].rstrip()
    signoff_text = "\n".join([
        marker, "",
        f"- DRC (KLayout): **{drc_status}** ({drc_count if drc_count is not None else 'not verified'})",
        f"- LVS (KLayout): **{lvs_status}**",
        f"- signoff accepted: **{bool(drc_status == 'clean' and lvs_status == 'match')}**",
        f"- DRC report: `{drc_report}`",
        f"- LVS report: `{lvs_report}`",
        "",
    ])
    md.write_text(old.rstrip() + "\n\n" + signoff_text)
    (signoff / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-sample", action="append")
    ap.add_argument("--only-platform", action="append")
    ap.add_argument("--skip-lvs", action="store_true",
                    help="run KLayout DRC only; LVS is recorded as 'skipped' "
                         "(gf180's LVS deck hangs indefinitely in this image)")
    args = ap.parse_args()
    manifest = load(MANIFEST, {}) or {}
    baseline_rows = load(BASELINE, {}).get("results", [])
    baseline = {x.get("sample_id"): x for x in baseline_rows}
    samples = manifest.get("samples", [])
    if args.only_sample:
        wanted = set(args.only_sample)
        samples = [x for x in samples if x["sample_id"] in wanted]
    if args.only_platform:
        wanted = set(args.only_platform)
        samples = [x for x in samples if x["platform"] in wanted]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        jobs = {ex.submit(execute, s, baseline, args.force, args.timeout,
                          args.skip_lvs): s["sample_id"] for s in samples}
        for job in concurrent.futures.as_completed(jobs):
            try:
                row = job.result()
            except Exception as exc:
                row = {"sample_id": jobs[job], "status": "exception", "error": repr(exc)}
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    out = NET2GDS / "reports/openlayout_43_klayout_signoff_20261103.json"
    out.write_text(json.dumps({"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               "total": len(results), "results": sorted(results, key=lambda x: x["sample_id"])},
                              indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"total": len(results), "report": str(out)}))
    return 0 if len(results) == len(samples) and all(x.get("status") == "complete" for x in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
