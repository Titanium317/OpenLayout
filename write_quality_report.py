#!/usr/bin/env python3
"""Write a compact artifact/quality report after an OpenLayout run."""

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--gds", required=True)
    ap.add_argument("--lvs", default="not verified")
    args = ap.parse_args()

    out = Path(args.output_dir).resolve()
    gds = Path(args.gds).resolve()
    metrics_path = out / "final_metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    fm = metrics.get("final_metrics", {})
    route = metrics.get("per_stage", {}).get("route", {})
    finish = metrics.get("per_stage", {}).get("finish", {})
    def artifact(path):
        return {"path": str(path), "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() else 0}

    artifacts = {
        "gds": artifact(gds),
        "quality_report_md": artifact(out / "report.md"),
        "final_metrics_json": artifact(metrics_path),
        "finish_odb": artifact(out / "saves_db" / "05_finish.odb"),
        "final_def": artifact(out / "saves_db" / (metrics.get("design", "design") + "_final.def")),
    }
    drc_value = fm.get("drc_violations")
    drc_count = int(drc_value) if drc_value is not None else None
    drc_report = out / "reports" / "route.drc.rpt"
    drc_state = ("clean" if drc_count == 0 else "violations") if drc_count is not None else ("unknown" if drc_report.exists() else "blocked")
    report = {
        "design": metrics.get("design", out.name),
        "flow_completed": artifacts["finish_odb"]["exists"] and artifacts["final_def"]["exists"],
        "gds_generated": artifacts["gds"]["exists"] and artifacts["gds"]["bytes"] > 0,
        "quality_report_generated": artifacts["quality_report_md"]["exists"],
        "quality": {
            "drc": drc_state,
            "drc_violations": drc_count,
            "lvs": args.lvs,
            "timing_closed": (float(fm.get("wns_setup", -1e9)) >= 0 and
                              float(fm.get("wns_hold", -1e9)) >= 0 and
                              float(fm.get("tns", -1e9)) >= 0),
            "wns_setup_ns": fm.get("wns_setup"),
            "wns_hold_ns": fm.get("wns_hold"),
            "tns_ns": fm.get("tns"),
            "route_status": route.get("status"),
            "finish_status": finish.get("status"),
        },
        "artifacts": artifacts,
    }
    (out / "quality_report.json").write_text(json.dumps(report, indent=2) + "\n")

    md = out / "report.md"
    text = md.read_text() if md.exists() else ""
    marker = "## Output artifacts"
    if marker not in text:
        lines = ["", marker, "",
                 "- flow completed: **%s**" % report["flow_completed"],
                 "- GDS generated: **%s** — `%s` (%d bytes)" %
                 (report["gds_generated"], gds, artifacts["gds"]["bytes"]),
                 "- quality report JSON: `%s`" % (out / "quality_report.json"),
                 "- DRC: **%s** (%s)" %
                 (report["quality"]["drc"],
                  report["quality"]["drc_violations"] if
                  report["quality"]["drc_violations"] is not None else "count unavailable"),
                 "- LVS: **%s**" % args.lvs,
                 "- timing closed: **%s** (WNS setup=%s ns, TNS=%s ns)" %
                 (report["quality"]["timing_closed"],
                  report["quality"]["wns_setup_ns"], report["quality"]["tns_ns"])]
        md.write_text(text.rstrip() + "\n" + "\n".join(lines) + "\n")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
