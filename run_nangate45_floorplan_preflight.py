from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import subprocess, json, re
root=Path('/data/taiyuzhou/OpenLayout'); cfgs=sorted((root/'configs/current43').glob('nangate45__*.yaml'))
py='/data/taiyuzhou/.venv/bin/python'
def one(cfg):
    p=subprocess.run([py,'run_openlayout.py','--config',str(cfg),'--stages','floorplan'],cwd=root,text=True,capture_output=True,timeout=600)
    out=p.stdout+p.stderr
    ok='[worker] done ok=True' in out
    m=re.search(r'metrics=(\{[^\n]+\})',out)
    return {'sample_id':cfg.stem,'ok':ok,'returncode':p.returncode,'metrics':m.group(1) if m else None,'tail':out[-500:]}
res=[]
with ThreadPoolExecutor(max_workers=1) as ex:
 futs=[ex.submit(one,c) for c in cfgs]
 for f in as_completed(futs):
  x=f.result(); res.append(x); print(x['sample_id'],x['ok'],x['metrics'],flush=True)
out=root/'output/current43/nangate45_floorplan_preflight.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(sorted(res,key=lambda x:x['sample_id']),indent=2))
print('report',out,'pass',sum(x['ok'] for x in res),'total',len(res))
