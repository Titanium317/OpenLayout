#!/usr/bin/env python3
"""Generate LLM-enabled OpenLayout configs for all fixed 43 samples."""
import json
from pathlib import Path

ROOT = Path('/data/taiyuzhou/net2GDS')
OL = Path('/data/taiyuzhou/OpenLayout')
MANIFEST = ROOT / 'reports/openlayout_43_manifest_20261102.json'
cfg_root = OL / 'configs/current43'

TECH = {
    'nangate45': {'dir': ROOT / 'OpenROAD-flow-scripts/flow/platforms/nangate45', 'stdcell_lib': 'NangateOpenCellLibrary_typical.lib', 'tech_lef': 'NangateOpenCellLibrary.tech.lef', 'cell_lef': 'NangateOpenCellLibrary.macro.mod.lef', 'site': 'FreePDK45_38x28_10R_NP_162NW_34O'},
    'gf180': {'dir': ROOT / 'OpenROAD-flow-scripts/flow/platforms/gf180', 'stdcell_lib': 'gf180mcu_fd_sc_mcu9t5v0__tt_025C_5v00.lib.gz', 'tech_lef': 'gf180mcu_5LM_1TM_9K_9t_tech.lef', 'cell_lef': 'gf180mcu_5LM_1TM_9K_9t_sc.lef', 'site': 'GF018hv5v_green_sc9'},
    'ihp-sg13g2': {'dir': ROOT / 'OpenROAD-flow-scripts/flow/platforms/ihp-sg13g2', 'stdcell_lib': 'sg13g2_stdcell_typ_1p20V_25C.lib', 'tech_lef': 'sg13g2_tech.lef', 'cell_lef': 'sg13g2_stdcell.lef', 'site': 'CoreSite'},
    'sky130hd': {'dir': ROOT / 'OpenROAD-flow-scripts/flow/platforms/sky130hd', 'stdcell_lib': 'sky130_fd_sc_hd__tt_025C_1v80.lib', 'tech_lef': 'sky130_fd_sc_hd.tlef', 'cell_lef': 'sky130_fd_sc_hd_merged.lef', 'site': 'unithd'},
    'sky130hs': {'dir': ROOT / 'OpenROAD-flow-scripts/flow/platforms/sky130hs', 'stdcell_lib': 'sky130_fd_sc_hs__tt_025C_1v80.lib', 'tech_lef': 'sky130_fd_sc_hs.tlef', 'cell_lef': 'sky130_fd_sc_hs_merged.lef', 'site': 'unit'},
}

def make_config(s):
    t = TECH[s['platform']]
    extra = ''
    if s['platform'] == 'gf180' and 'gf180mcu_fd_sc_mcu7t5v0' in Path(s['netlist']).read_text(errors='ignore'):
        d = t['dir']
        extra = ('\n  extra_cell_lefs:\n'
                 f'    - {d.resolve()}/lef/gf180mcu_5LM_1TM_9K_7t_sc.lef\n'
                 '  extra_libs:\n'
                 f'    - {d.resolve()}/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib.gz')
    if s['platform'] == 'sky130hd' and s['design'] == 'chameleon':
        d = ROOT / 'OpenROAD-flow-scripts/flow/designs/sky130hd/chameleon'
        extra = ('\n  extra_cell_lefs:\n' +
                 ''.join(f'    - {p}\n' for p in sorted((d / 'lef').glob('*.lef'))) +
                 '  extra_libs: []')
    return f'''design:
  name: {s['design']}
  top: {s['top']}
  data_dir: Benchmark/CurrentNet2GDS43/{s['sample_id']}
  netlist: netlist.v
  sdc: constraint.sdc
  floorplan_def: ""
  cluster_file: null
paths:
  output_dir: output/current43/{s['sample_id']}
  image_dir: output/current43/{s['sample_id']}/images
goal:
  timing_met: true
  drc_clean: true
  max_wns: 0.0
  priority: [timing, drc, tns, placement, wirelength, power, area]
tech:
  platform: {s['platform']}
  dir: {t['dir'].resolve()}
  stdcell_lib: {t['stdcell_lib']}
  tech_lef: {t['tech_lef']}
  cell_lef: {t['cell_lef']}
  site: {t['site']}
{extra}
skills:
  flow_dir: skills/skills_openroad_flow
image:
  width: 1024
  margin: 0.03
llm:
  provider: openai
  model: deepseek-flash
  api_key_file: /data/taiyuzhou/net2GDS/eda-agent/.env
  base_url: https://api.deepseek.com
  max_output_tokens: 8192
  max_attempts: 1
  timeout: 180
macro_stage:
  enable: false
  candidates: 1
  parallel_workers: 1
stages:
  - {{name: floorplan, optimizer_budget: 0}}
  - {{name: macro_place, optimizer_budget: 0}}
  - {{name: detail_place, optimizer_budget: 0}}
  - {{name: cts, optimizer_budget: 0}}
  - {{name: route, optimizer_budget: 0}}
  - {{name: finish, optimizer_budget: 0}}
agents:
  optimizer_suggestions: 0
  debugger_extra_budget: 1
  parallel_eval: false
  allow_tool_queries: false
  max_queries: 0
openroad:
  executable: /data/taiyuzhou/OpenLayout/openroad_container.sh
  threads: 8
  timeout_s: 7200
'''

def main():
    samples = json.loads(MANIFEST.read_text())['samples']
    cfg_root.mkdir(parents=True, exist_ok=True)
    for sample in samples:
        (cfg_root / (sample['sample_id'] + '.yaml')).write_text(make_config(sample))
    print('generated', len(samples), 'configs')


if __name__ == '__main__':
    main()
