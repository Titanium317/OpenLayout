#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path
ROOT=Path('/data/taiyuzhou/net2GDS'); OL=Path('/data/taiyuzhou/OpenLayout')
manifest=json.loads((ROOT/'reports/openlayout_43_manifest_20261102.json').read_text())
out_root=OL/'Benchmark/CurrentNet2GDS43'; cfg_root=OL/'configs/current43'; out_root.mkdir(parents=True,exist_ok=True); cfg_root.mkdir(parents=True,exist_ok=True)
for x in manifest['samples']:
    sid=x['sample_id']; p=out_root/sid; p.mkdir(parents=True,exist_ok=True)
    for name,src in [('netlist.v',Path(x['netlist'])),('constraint.sdc',Path(x['sdc']))]:
        dst=p/name
        if src.exists() and not dst.exists(): dst.symlink_to(src)
    platform_dir=ROOT/'OpenROAD-flow-scripts/flow/platforms'/x['platform']
    for sub in ['lef','lib']:
        dst=p/sub
        if not dst.exists(): dst.symlink_to(platform_dir/sub)
    if x['platform']=='nangate45':
        cfg=f'''design:\n  name: {x['design']}\n  top: {x['top']}\n  data_dir: Benchmark/CurrentNet2GDS43/{sid}\n  netlist: netlist.v\n  sdc: constraint.sdc\n  floorplan_def: ""\n  cluster_file: null\npaths:\n  output_dir: output/current43/{sid}\n  image_dir: output/current43/{sid}/images\ngoal:\n  timing_met: true\n  drc_clean: true\n  max_wns: 0.0\n  priority: [timing, drc, tns, placement, wirelength, power, area]\ntech:\n  dir: Digital_lib/Nangate45\nskills:\n  flow_dir: skills/skills_openroad_flow\nimage:\n  width: 1024\n  margin: 0.03\nllm:\n  provider: openai\n  model: deepseek-flash\n  api_key_file: /data/taiyuzhou/net2GDS/eda-agent/.env\n  base_url: https://api.deepseek.com\n  max_output_tokens: 8192\n  max_attempts: 1\n  timeout: 180\nmacro_stage:\n  enable: false\n  candidates: 1\n  parallel_workers: 1\nstages:\n  - {{name: floorplan, optimizer_budget: 0}}\n  - {{name: macro_place, optimizer_budget: 0}}\n  - {{name: detail_place, optimizer_budget: 0}}\n  - {{name: cts, optimizer_budget: 0}}\n  - {{name: route, optimizer_budget: 0}}\n  - {{name: finish, optimizer_budget: 0}}\nagents:\n  optimizer_suggestions: 0\n  debugger_extra_budget: 0\n  parallel_eval: false\n  allow_tool_queries: false\n  max_queries: 0\nopenroad:\n  executable: /data/taiyuzhou/OpenLayout/openroad_container.sh\n  threads: 8\n  timeout_s: 7200\n'''
        (cfg_root/(sid+'.yaml')).write_text(cfg)
print('prepared',len(manifest['samples']),'adapter directories')
print('nangate45 configs',sum(x['platform']=='nangate45' for x in manifest['samples']))
