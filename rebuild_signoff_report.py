"""Merge the per-sample signoff results and rebuild the 43-design comparison.

The signoff runner writes the aggregate report itself, but the DRC pass and the
LVS pass were run as separate processes (gf180 hangs LVS), so each wrote only
its own subset.  Every design nevertheless has an authoritative
``output/current43/<sid>/signoff/summary.json``; this script rebuilds the
aggregate from those and then regenerates the OpenLayout-vs-user-agent table.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path('/data/taiyuzhou')
OUT_ROOT = ROOT / 'OpenLayout/output/current43'
REPORTS = ROOT / 'net2GDS/reports'
SIGNOFF = REPORTS / 'openlayout_43_klayout_signoff_20261103.json'
BASELINE = REPORTS / 'final_tasks_signoff.json'
CMP_JSON = REPORTS / 'openlayout_vs_user_agent_43_klayout_comparison_20261103.json'
CMP_MD = REPORTS / 'openlayout_vs_user_agent_43_klayout_comparison_20261103.md'


def main() -> int:
    rows = []
    for p in sorted(OUT_ROOT.glob('*/signoff/summary.json')):
        rows.append(json.loads(p.read_text()))
    rows.sort(key=lambda r: r['sample_id'])
    SIGNOFF.write_text(json.dumps({
        'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'total': len(rows),
        'results': rows,
    }, indent=2, ensure_ascii=False) + '\n')
    print(f'merged {len(rows)} signoff rows -> {SIGNOFF}')

    base = {r['sample_id']: r for r in json.loads(BASELINE.read_text())['results']}
    out = []
    for r in rows:
        b = base.get(r['sample_id'], {})
        out.append({
            'sample_id': r['sample_id'],
            'platform': r['platform'],
            'design': r['design'],
            'drc_violations': r['drc']['violations'],
            'drc_status': r['drc']['status'],
            'lvs_status': r['lvs']['status'],
            'user_agent': {
                'drc_clean': bool((b.get('drc') or {}).get('clean')),
                'lvs': (b.get('lvs') or {}).get('status'),
                'timing_closed': (b.get('final_qor') or {}).get('timing_closed'),
            },
        })

    def summary(rows_, key):
        c = Counter(key(x) for x in rows_)
        return dict(c)

    md = ['# OpenLayout vs 用户 Agent：43 个设计 GDS 质量对比（KLayout signoff，修复后重跑）', '',
          f'生成时间：{time.strftime("%Y-%m-%d %H:%M")}　|　样本：{len(out)}', '',
          '> 本表由 2026-11-05/06 的全量重跑生成，取代 2026-11-03 的版本。',
          '> 修复内容：DEF→GDS 加载 LEF、filler/tap 插入、18 个设计的顶层模块、',
          '> gf180 9t layermap、DRC clean 计数（按 `<item>`）。', '',
          '## 总览', '',
          '| 指标 | OpenLayout（修复后） | 用户 Agent |',
          '|---|---:|---:|',
          f'| DRC clean | **{sum(1 for x in out if x["drc_status"] == "clean")}/{len(out)}** | '
          f'{sum(1 for x in out if x["user_agent"]["drc_clean"])}/{len(out)} |',
          f'| LVS match | {sum(1 for x in out if x["lvs_status"] == "match")}/{len(out)} | '
          f'{sum(1 for x in out if x["user_agent"]["lvs"] == "match")}/{len(out)} |',
          '']
    by_plat = defaultdict(list)
    for x in out:
        by_plat[x['platform']].append(x)
    md += ['## 按平台', '', '| 平台 | 数量 | OpenLayout DRC clean | 用户 Agent DRC clean | 中位违规数 |',
           '|---|---:|---:|---:|---:|']
    for p, xs in sorted(by_plat.items()):
        vals = sorted(x['drc_violations'] for x in xs if x['drc_violations'] is not None)
        med = vals[len(vals) // 2] if vals else '-'
        md.append(f'| {p} | {len(xs)} | {sum(1 for x in xs if x["drc_status"] == "clean")} | '
                  f'{sum(1 for x in xs if x["user_agent"]["drc_clean"])} | {med} |')
    md += ['', '## 逐设计', '', '| 设计 | 平台 | DRC | 状态 | LVS |', '|---|---|---:|---|---|']
    for x in sorted(out, key=lambda y: (y['drc_violations'] is None, y['drc_violations'] or 0)):
        md.append(f"| `{x['sample_id']}` | {x['platform']} | {x['drc_violations']} | "
                  f"{x['drc_status']} | {x['lvs_status']} |")
    md += ['', '## 已知限制', '',
           '- gf180：版图 DRC 达 10^5 量级（`PP.5a`/`CO.*`），层映射仍未修好，结果不可采信。',
           '- `ihp-sg13g2__gcd`：netlist 使用 `sg13g2_a21o_*` 等 30 个单元，平台 LEF 中不存在。',
           '- `sky130hd__microwatt`：缺 `RAM512` 等宏 LEF，无可用的最终 DEF。',
           '- LVS 全部 mismatch/timeout：布线未收敛（中位 DRC 上万条），且大设计 900 s 超时。', '']
    CMP_MD.write_text('\n'.join(md))
    CMP_JSON.write_text(json.dumps({'generated_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                    'total': len(out), 'results': out},
                                   indent=2, ensure_ascii=False) + '\n')
    print(f'wrote {CMP_MD.name} and {CMP_JSON.name}')
    print('drc status:', dict(Counter(x['drc_status'] for x in out)))
    print('lvs status:', dict(Counter(x['lvs_status'] for x in out)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
