"""Flow configuration — one YAML file records paths, per-stage budgets,
design goals, LLM provider and agent knobs.  Everything the user should be
able to edit lives here; see ``configs/bp_fe.yaml`` for the reference file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _expand(v: str | None) -> str | None:
    if v is None:
        return None
    return os.path.expandvars(os.path.expanduser(str(v)))


@dataclass
class StageBudget:
    name: str
    optimizer_budget: int = 3
    # debugger budget = optimizer_budget + debugger_extra (set flow-wide)


@dataclass
class FlowConfig:
    raw: dict = field(default_factory=dict)
    config_path: Path | None = None

    # --- design ---
    design: str = "bp_fe"
    top: str = "bp_fe_top"
    data_dir: Path = Path(".")
    netlist: str = ""                 # relative to data_dir unless absolute
    sdc: str = "constraint.sdc"
    floorplan_def: str = ""           # predefined floorplan DEF (rel to data_dir)
    cluster_file: str | None = None

    # --- paths ---
    output_dir: Path = Path("output")
    image_dir: Path | None = None

    # --- goal ---
    goal: dict = field(default_factory=dict)

    # --- llm ---
    llm: dict = field(default_factory=dict)

    # --- macro stage ---
    macro: dict = field(default_factory=dict)

    # --- stages/budgets ---
    stages: list[StageBudget] = field(default_factory=list)

    # --- agents ---
    optimizer_suggestions: int = 2
    debugger_extra_budget: int = 1
    parallel_eval: bool = True
    allow_tool_queries: bool = True
    max_queries: int = 4

    # --- skills ---
    skills_flow_dir: str = "skills/skills_openroad_flow"

    # --- technology files (std-cell lib + tech/cell LEF) ---
    tech_dir: Path | None = None      # None -> fall back to data_dir

    # --- openroad ---
    openroad_exe: str = "openroad"
    threads: int = 8
    tool_timeout_s: int = 7200

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "FlowConfig":
        path = Path(path).resolve()
        raw = yaml.safe_load(path.read_text()) or {}
        cfg = cls(raw=raw, config_path=path)

        d = raw.get("design", {})
        cfg.design = d.get("name", cfg.design)
        cfg.top = d.get("top", cfg.top)
        cfg.data_dir = Path(_expand(d.get("data_dir", "."))).resolve()
        cfg.netlist = d.get("netlist", f"{cfg.design}.v")
        cfg.sdc = d.get("sdc", "constraint.sdc")
        cfg.floorplan_def = d.get("floorplan_def", "")
        cfg.cluster_file = _expand(d.get("cluster_file"))

        p = raw.get("paths", {})
        cfg.output_dir = Path(_expand(p.get("output_dir", "output"))).resolve()
        img = p.get("image_dir")
        cfg.image_dir = Path(_expand(img)).resolve() if img else \
            cfg.output_dir / "images"

        cfg.goal = raw.get("goal", {"timing_met": True, "drc_clean": True})
        cfg.llm = raw.get("llm", {})
        cfg.macro = raw.get("macro_stage", {})

        for s in raw.get("stages", []):
            cfg.stages.append(StageBudget(
                name=s["name"],
                optimizer_budget=int(s.get("optimizer_budget", 3)),
            ))

        a = raw.get("agents", {})
        cfg.optimizer_suggestions = int(a.get("optimizer_suggestions", 2))
        cfg.debugger_extra_budget = int(a.get("debugger_extra_budget", 1))
        cfg.parallel_eval = bool(a.get("parallel_eval", True))
        cfg.allow_tool_queries = bool(a.get("allow_tool_queries", True))
        cfg.max_queries = int(a.get("max_queries", 4))

        sk = raw.get("skills", {})
        cfg.skills_flow_dir = sk.get("flow_dir", cfg.skills_flow_dir)

        t = raw.get("tech", {}) or {}
        td = _expand(t.get("dir"))
        if td:
            tp = Path(td)
            cfg.tech_dir = (tp if tp.is_absolute() else PROJECT_ROOT / tp).resolve()

        o = raw.get("openroad", {})
        cfg.openroad_exe = o.get("executable", "openroad")
        cfg.threads = int(o.get("threads", 8))
        cfg.tool_timeout_s = int(o.get("timeout_s", 7200))
        return cfg

    # ------------------------------------------------------------------
    def budget_for(self, stage: str) -> StageBudget:
        for s in self.stages:
            if s.name == stage:
                return s
        return StageBudget(name=stage)

    def stage_names(self) -> list[str]:
        return [s.name for s in self.stages]

    @property
    def goal_priority(self) -> list[str]:
        """Metric priority order for selecting the best attempt (config:
        goal.priority). Timing first by default."""
        pr = self.goal.get("priority")
        if isinstance(pr, list) and pr:
            return [str(p) for p in pr]
        return ["timing", "drc", "tns", "placement", "wirelength",
                "power", "area"]

    # resolved paths ----------------------------------------------------
    @property
    def netlist_path(self) -> Path:
        p = Path(self.netlist)
        return p if p.is_absolute() else self.data_dir / p

    @property
    def sdc_path(self) -> Path:
        p = Path(self.sdc)
        return p if p.is_absolute() else self.data_dir / p

    @property
    def floorplan_def_path(self) -> Path:
        p = Path(self.floorplan_def)
        return p if p.is_absolute() else self.data_dir / p

    @property
    def tech_dir_path(self) -> Path:
        """Directory holding ``lib/`` and ``lef/`` of the PDK (config
        ``tech.dir``); defaults to the design data dir."""
        return self.tech_dir or self.data_dir

    @property
    def platform(self) -> str:
        """Technology platform identifier used by the stage templates."""
        t = self.raw.get("tech", {}) or {}
        return str(t.get("platform", "nangate45")).lower()

    def _tech_option(self, name: str, default: str = "") -> str:
        t = self.raw.get("tech", {}) or {}
        return str(t.get(name, default) or default)

    @property
    def extra_cell_lefs(self) -> list[Path]:
        vals = self.raw.get("tech", {}).get("extra_cell_lefs", []) or []
        return [Path(v).resolve() for v in vals]

    @property
    def extra_libs(self) -> list[Path]:
        vals = self.raw.get("tech", {}).get("extra_libs", []) or []
        return [Path(v).resolve() for v in vals]

    @property
    def stdcell_lib(self) -> Path:
        explicit = self._tech_option("stdcell_lib")
        if explicit:
            p = Path(explicit)
            return p if p.is_absolute() else self.tech_dir_path / "lib" / p
        p = self.tech_dir_path / "lib"
        names = {
            "nangate45": "NangateOpenCellLibrary_typical.lib",
            "gf180": "gf180mcu_fd_sc_mcu9t5v0__tt_025C_5v00.lib.gz",
            "ihp-sg13g2": "sg13g2_stdcell_typ_1p20V_25C.lib",
            "sky130hd": "sky130_fd_sc_hd__tt_025C_1v80.lib",
            "sky130hs": "sky130_fd_sc_hs__tt_025C_1v80.lib",
        }
        candidate = p / names.get(self.platform, "NangateOpenCellLibrary_typical.lib")
        if candidate.exists():
            return candidate
        hits = sorted(list(p.glob("*.lib")) + list(p.glob("*.lib.gz")))
        if not hits:
            return candidate
        # Prefer a standard-cell liberty over SRAM/IO macro libraries.
        preferred = [h for h in hits if any(k in h.name.lower() for k in
                    ("stdcell", "sc_", "fd_sc", "nangate"))]
        return (preferred or hits)[0]

    @property
    def tech_lef(self) -> Path:
        explicit = self._tech_option("tech_lef")
        if explicit:
            p = Path(explicit)
            return p if p.is_absolute() else self.tech_dir_path / "lef" / p
        p = self.tech_dir_path / "lef"
        names = {
            "nangate45": "NangateOpenCellLibrary.tech.lef",
            "gf180": "gf180mcu_5LM_1TM_9K_9t_tech.lef",
            "ihp-sg13g2": "sg13g2_tech.lef",
            "sky130hd": "sky130_fd_sc_hd.tlef",
            "sky130hs": "sky130_fd_sc_hs.tlef",
        }
        return p / names.get(self.platform, "NangateOpenCellLibrary.tech.lef")

    @property
    def cell_lef(self) -> Path:
        explicit = self._tech_option("cell_lef")
        if explicit:
            p = Path(explicit)
            return p if p.is_absolute() else self.tech_dir_path / "lef" / p
        p = self.tech_dir_path / "lef"
        names = {
            "nangate45": "NangateOpenCellLibrary.macro.mod.lef",
            "gf180": "gf180mcu_5LM_1TM_9K_9t_sc.lef",
            "ihp-sg13g2": "sg13g2_stdcell.lef",
            "sky130hd": "sky130_fd_sc_hd_merged.lef",
            "sky130hs": "sky130_fd_sc_hs_merged.lef",
        }
        return p / names.get(self.platform, "NangateOpenCellLibrary.macro.mod.lef")

    @property
    def site_name(self) -> str:
        explicit = self._tech_option("site")
        if explicit:
            return explicit
        return {
            "nangate45": "FreePDK45_38x28_10R_NP_162NW_34O",
            "gf180": "GF018hv5v_green_sc9",
            "ihp-sg13g2": "CoreSite",
            "sky130hd": "unithd",
            "sky130hs": "unit",
        }.get(self.platform, "FreePDK45_38x28_10R_NP_162NW_34O")

    @property
    def platform_stage_defaults(self) -> dict:
        """Layer/cell knobs shared by all templates for this PDK."""
        p = self.platform
        if p == "gf180":
            return {"rc_signal_layer": "Metal3", "rc_clock_layer": "Metal4",
                    "sig_min_layer": "Metal2", "sig_max_layer": "Metal5",
                    "clk_min_layer": "Metal3", "clk_max_layer": "Metal5",
                    "place_pin_h": "Metal3", "place_pin_v": "Metal2",
                    "root_buf": "gf180mcu_fd_sc_mcu9t5v0__clkbuf_4",
                    "buf_list": "gf180mcu_fd_sc_mcu9t5v0__buf_2 gf180mcu_fd_sc_mcu9t5v0__buf_4 gf180mcu_fd_sc_mcu9t5v0__buf_8",
                    "fill_cells": "gf180mcu_fd_sc_mcu9t5v0__fill_1 gf180mcu_fd_sc_mcu9t5v0__fill_2 gf180mcu_fd_sc_mcu9t5v0__fill_4 gf180mcu_fd_sc_mcu9t5v0__fill_8 gf180mcu_fd_sc_mcu9t5v0__fill_16 gf180mcu_fd_sc_mcu9t5v0__fill_32 gf180mcu_fd_sc_mcu9t5v0__fill_64",
                    "tap_cell": "gf180mcu_fd_sc_mcu9t5v0__filltie",
                    "tap_distance": 14,
                    "repair_setup": 0, "repair_hold": 0,
                    "post_grt_repair_design": 0, "post_grt_repair_setup": 0,
                    "post_grt_repair_hold": 0,
                    "skip_pdn": 1}
        if p == "ihp-sg13g2":
            return {"rc_signal_layer": "Metal3", "rc_clock_layer": "Metal4",
                    "sig_min_layer": "Metal2", "sig_max_layer": "Metal5",
                    "clk_min_layer": "Metal3", "clk_max_layer": "Metal5",
                    "place_pin_h": "Metal3", "place_pin_v": "Metal2",
                    "root_buf": "sg13g2_buf_4",
                    "buf_list": "sg13g2_buf_1 sg13g2_buf_2 sg13g2_buf_4",
                    "fill_cells": "sg13g2_fill_1 sg13g2_fill_2 sg13g2_decap_4 sg13g2_decap_8",
                    "tap_cell": "",
                    "tap_distance": 14,
                    "repair_setup": 0, "repair_hold": 0,
                    "post_grt_repair_design": 0, "post_grt_repair_setup": 0,
                    "post_grt_repair_hold": 0,
                    "skip_pdn": 1}
        if p in ("sky130hd", "sky130hs"):
            pre = "sky130_fd_sc_hd__" if p == "sky130hd" else "sky130_fd_sc_hs__"
            return {"rc_signal_layer": "met3", "rc_clock_layer": "met4",
                    "sig_min_layer": "met1", "sig_max_layer": "met5",
                    "clk_min_layer": "met3", "clk_max_layer": "met5",
                    "place_pin_h": "met3", "place_pin_v": "met2",
                    "root_buf": pre + "clkbuf_4",
                    "buf_list": pre + "buf_1 " + pre + "buf_2 " + pre + "buf_4",
                    "fill_cells": " ".join(pre + f"fill_{n}" for n in (1, 2, 4, 8)),
                    "tap_cell": pre + "tapvpwrvgnd_1",
                    "tap_distance": 14,
                    "repair_setup": 0, "repair_hold": 0,
                    "post_grt_repair_design": 0, "post_grt_repair_setup": 0,
                    "post_grt_repair_hold": 0,
                    "skip_pdn": 1}
        return {"rc_signal_layer": "metal3", "rc_clock_layer": "metal5",
                "sig_min_layer": "metal2", "sig_max_layer": "metal9",
                "clk_min_layer": "metal3", "clk_max_layer": "metal8",
                "place_pin_h": "metal3", "place_pin_v": "metal2",
                "root_buf": "CLKBUF_X3",
                "buf_list": "CLKBUF_X1 CLKBUF_X2 CLKBUF_X3",
                "fill_cells": "FILLCELL_X1 FILLCELL_X2 FILLCELL_X4 FILLCELL_X8 FILLCELL_X16 FILLCELL_X32",
                "tap_cell": "TAPCELL_X1",
                "tap_distance": 14,
                "skip_pdn": 0}

    @property
    def save_dir(self) -> Path:
        return self.output_dir / "saves_db"

    @property
    def report_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def log_dir(self) -> Path:
        return self.output_dir / "logs"

    @property
    def gen_dir(self) -> Path:
        return self.output_dir / "generated_scripts"

    @property
    def dialog_dir(self) -> Path:
        return self.output_dir / "dialogs"

    def make_dirs(self) -> None:
        for p in (self.output_dir, self.save_dir, self.report_dir,
                  self.log_dir, self.gen_dir, self.dialog_dir,
                  self.image_dir):
            Path(p).mkdir(parents=True, exist_ok=True)

    # llm helpers -------------------------------------------------------
    def resolve_api_key(self) -> str | None:
        # the configured key file wins over a (possibly stale) env var
        kf = self.llm.get("api_key_file")
        if kf:
            p = Path(_expand(kf))
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            if p.exists():
                for tok in p.read_text().split():
                    if tok.startswith("sk-"):
                        return tok.strip()
                return p.read_text().strip()
        env = os.environ.get("OPENAI_API_KEY")
        if env:
            return env.strip()
        return self.llm.get("api_key")
