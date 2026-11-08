"""Details: floor composition (latest api-request-shape), cache-bust causes, tool-call parallelism."""
import json, os, sys, collections, datetime as dt
H = os.path.expanduser('~'); B = chr(92)
ROOT = B + B + '?' + B + os.path.join(H, '.claude', 'projects')
since = sys.argv[1]
def ts(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
latest = None; busts = []; par = collections.Counter(); seq_tools = collections.Counter()
for dp, dn, fn in os.walk(ROOT):
    for f in fn:
        if not f.endswith('.jsonl'): continue
        p = os.path.join(dp, f)
        if dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d') < since: continue
        prev = None; between = []; seen = set(); first = True
        for line in open(p, encoding='utf-8', errors='replace'):
            try: d = json.loads(line)
            except Exception: continue
            t = d.get('timestamp') or ''
            if t and t[:10] < since: continue
            ty = d.get('type')
            if ty == 'api-request-shape' and (latest is None or t > latest[0]): latest = (t, d.get('shape'))
            if ty == 'system' and 'compact' in str(d.get('subtype')): first = True
            if ty in ('attachment', 'system'): between.append((d.get('attachment') or {}).get('type') or 'sys:' + str(d.get('subtype')))
            if ty != 'assistant': continue
            m = d.get('message') or {}; u = m.get('usage'); rid = d.get('requestId') or m.get('id')
            c = m.get('content') or []
            nt = sum(1 for b in c if isinstance(b, dict) and b.get('type') == 'tool_use')
            if rid in seen:
                par[rid] = par.get(rid, 0) + nt; continue
            seen.add(rid); par[rid] = nt
            if not u: continue
            cw = u.get('cache_creation_input_tokens', 0) or 0; cr = u.get('cache_read_input_tokens', 0) or 0
            T = ts(t)
            if prev and not first and cw > 30000 and T - prev[0] <= 3600:
                busts.append(dict(f=f[:8], gap=int(T - prev[0]), cw=cw, cr=cr, model=(prev[1], m.get('model')),
                                  eff=(prev[2], d.get('effort')), att=collections.Counter(between).most_common(6)))
            prev = (T, m.get('model'), d.get('effort')); between = []; first = False
shape = latest[1] if latest else {}
print('== FLOOR (latest request shape', latest[0] if latest else '-', ') ==')
for k, v in (shape or {}).items():
    s = json.dumps(v, ensure_ascii=False); print(f'  {k:12s} {len(s) // 4 / 1e3:6.1f}K tok')
tools = (shape or {}).get('tools') or []
rows = sorted(((t.get('name', '?'), len(json.dumps(t, ensure_ascii=False)) // 4) for t in tools if isinstance(t, dict)), key=lambda x: -x[1])
print('  tools n=', len(rows), ' top:', ', '.join(f'{n}:{k / 1e3:.1f}K' for n, k in rows[:14]))
sysb = (shape or {}).get('system') or []
for b in sysb if isinstance(sysb, list) else []:
    tx = b.get('text', '') if isinstance(b, dict) else str(b)
    print('  system block', len(tx) // 4, 'tok :', tx[:70].replace('\n', ' '))
print('\n== MID-SESSION CACHE BUSTS (>30K write, gap<=1h) n=', len(busts))
for b in busts[:30]: print(' ', b)
print('\n== TOOL CALLS PER REQUEST ==')
cnt = collections.Counter(min(v, 5) for v in par.values()); tot = sum(cnt.values())
for k in sorted(cnt): print(f'  {k}{"+" if k == 5 else ""} tool calls: {100 * cnt[k] / tot:5.1f}% of requests')
