"""ClaudeLimit: read-only root-cause analysis of token/limit drain over local Claude Code transcripts.
usage: drain.py SINCE(YYYY-MM-DD) [--until=YYYY-MM-DD]     (details: drain_detail.py SINCE)
Cost units (Pro weights): input 1, cache write 2 (1h), cache read 0.1, output 5. 5h window ~10M.
"""
import json, os, sys, collections, datetime as dt, statistics as st
H = os.path.expanduser('~'); B = chr(92)
ROOT = B + B + '?' + B + os.path.join(H, '.claude', 'projects')
since = sys.argv[1]; until = '9999'
for a in sys.argv[2:]:
    if a.startswith('--until='): until = a[8:]
W = dict(inp=1, cw=2, cr=0.1, out=5)
def ts(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
def tok(x): return len(x) // 4 if isinstance(x, str) else len(json.dumps(x, ensure_ascii=False)) // 4

reqs = []                       # one row per API request
carry = collections.Counter()   # cache-read cost attributed by content category
wcost = collections.Counter()   # cache-write cost by cause
addtok = collections.Counter()  # tokens added to context by category
qsrc = collections.Counter(); att_types = collections.Counter(); hooks_tok = collections.Counter()
turns = []                      # (session, n_requests, cost) per user prompt
files = 0
for dp, dn, fn in os.walk(ROOT):
    for f in fn:
        if not f.endswith('.jsonl'): continue
        p = os.path.join(dp, f)
        if dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d') < since: continue
        sub = 'subagents' in p; proj = p.split(B + 'projects' + B)[1].split(B)[0][-28:]
        files += 1
        items = collections.Counter(); seen = set(); tooln = {}; last_t = None; first = True
        turn = None; after_compact = False
        recs = []
        for line in open(p, encoding='utf-8', errors='replace'):
            try: d = json.loads(line)
            except Exception: continue
            t = d.get('timestamp') or ''
            if t and not (since <= t[:10] <= until): continue
            recs.append(d)
        for d in recs:
            ty = d.get('type')
            if ty == 'api-request': qsrc[d.get('querySource')] += 1; continue
            if ty == 'system' and 'compact' in str(d.get('subtype')):
                items.clear(); after_compact = True; continue
            if ty == 'attachment':
                a = d.get('attachment') or {}; k = a.get('type', '?')
                rd = d.get('rendered')
                if not rd: continue          # not sent to the model (transcript-only record)
                n = tok(rd); att_types[k] += n
                if k == 'hook_additional_context':
                    hn = str(a.get('hookName') or a.get('hookEvent') or '?')
                    hooks_tok[hn] += n; k = 'hook:' + hn
                items['att:' + k] += n; addtok['att:' + k] += n; continue
            m = d.get('message') or {}
            c = m.get('content')
            if ty == 'user':
                if isinstance(c, str) or (isinstance(c, list) and any(isinstance(b, dict) and b.get('type') == 'text' for b in c) and not any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c)):
                    if turn and not sub: turns.append(turn)
                    turn = [proj, 0, 0.0]
                    n = tok(c); items['user_prompt'] += n; addtok['user_prompt'] += n
                for b in c if isinstance(c, list) else []:
                    if isinstance(b, dict) and b.get('type') == 'tool_result':
                        nm = tooln.get(b.get('tool_use_id'), '?')
                        if nm.startswith('mcp__'): nm = 'mcp:' + nm.split('__')[1][:20]
                        n = tok(b.get('content')); items['tool:' + nm] += n; addtok['tool:' + nm] += n
                continue
            if ty != 'assistant': continue
            for b in c if isinstance(c, list) else []:
                if isinstance(b, dict) and b.get('type') == 'tool_use': tooln[b.get('id')] = b.get('name', '?')
            u = m.get('usage'); rid = d.get('requestId') or m.get('id')
            if not u or rid in seen: continue
            seen.add(rid)
            i, cw, cr, o = (u.get(k, 0) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'))
            th = ((u.get('output_tokens_details') or {}).get('thinking_tokens') or 0)
            T = ts(d['timestamp']); gap = (T - last_t) if last_t else None
            cost = W['inp'] * i + W['cw'] * cw + W['cr'] * cr + W['out'] * o
            cause = ('start' if first else 'compact' if after_compact else
                     'idle>1h' if gap and gap > 3600 else 'bust>30K' if cw > 30000 else 'incremental')
            wcost[cause] += W['cw'] * cw + W['inp'] * i
            # attribute cache-read cost to what is in context
            ctx = cr + cw + i; known = sum(items.values())
            floor = max(ctx - known, 0); tot = max(known + floor, 1)
            carry['floor(system+tools+early)'] += W['cr'] * cr * floor / tot
            for k, v in items.items(): carry[k] += W['cr'] * cr * v / tot
            items['thinking'] += th; items['assistant_visible'] += max(o - th, 0)
            addtok['thinking'] += th; addtok['assistant_visible'] += max(o - th, 0)
            reqs.append(dict(t=T, day=d['timestamp'][:10], proj=proj, sub=sub, eff=d.get('effort'),
                             model=m.get('model') or d.get('requestedModel'), i=i, cw=cw, cr=cr, o=o, th=th,
                             cost=cost, ctx=ctx, cause=cause, it=len(u.get('iterations') or []),
                             gap=gap, first=first))
            if turn and not sub: turn[1] += 1; turn[2] += cost
            last_t = T; first = False; after_compact = False
        if turn and not sub: turns.append(turn)

tc = sum(r['cost'] for r in reqs) or 1
def pc(x): return f'{100 * x / tc:5.1f}%'
print(f'files {files}  requests {len(reqs)}  total cost {tc / 1e6:.1f}M units  (~{tc / 10e6:.1f} five-hour windows)')
O = sum(W['out'] * r['o'] for r in reqs); TH = sum(W['out'] * r['th'] for r in reqs)
R = sum(W['cr'] * r['cr'] for r in reqs); CW = sum(W['cw'] * r['cw'] + r['i'] for r in reqs)
print(f'\n== COST SPLIT ==\noutput {pc(O)}  (thinking {pc(TH)}, visible+tool calls {pc(O - TH)})\ncache read {pc(R)}\ncache write {pc(CW)}')
print('\n== CACHE WRITE BY CAUSE ==')
for k, v in wcost.most_common(): print(f'  {k:12s} {pc(v)}  n={sum(1 for r in reqs if r["cause"] == k)}')
print('\n== CACHE READ ATTRIBUTED TO CONTENT (carry cost) ==')
for k, v in carry.most_common(18): print(f'  {k:34s} {pc(v)}   added {addtok.get(k, 0) / 1e3:8.0f}K tok')
print('\n== SUBAGENTS vs MAIN ==')
for s in (False, True):
    rs = [r for r in reqs if r['sub'] == s]; print(f'  sub={s}: n={len(rs)} cost {pc(sum(r["cost"] for r in rs))}')
print('\n== BY EFFORT ==')
for e in sorted({str(r['eff']) for r in reqs}):
    rs = [r for r in reqs if str(r['eff']) == e and not r['sub']]
    if rs: print(f'  {e:7s} n={len(rs):5d} cost {pc(sum(r["cost"] for r in rs))}  per-req {st.mean(r["cost"] for r in rs) / 1e3:5.1f}K  out/req {st.mean(r["o"] for r in rs):6.0f}  think/req {st.mean(r["th"] for r in rs):6.0f}  med ctx {st.median(r["ctx"] for r in rs) / 1e3:.0f}K')
print('\n== BY MODEL ==')
for mo, n in collections.Counter(r['model'] for r in reqs).most_common():
    print(f'  {mo}: n={n} cost {pc(sum(r["cost"] for r in reqs if r["model"] == mo))}')
print('\n== CONTEXT SIZE BANDS (main) ==')
for lo, hi in ((0, 80e3), (80e3, 120e3), (120e3, 160e3), (160e3, 200e3), (200e3, 1e9)):
    rs = [r for r in reqs if lo <= r['ctx'] < hi and not r['sub']]
    print(f'  {int(lo / 1e3):4d}-{int(min(hi, 999e3) / 1e3):3d}K n={len(rs):5d} cost {pc(sum(r["cost"] for r in rs))}')
print('\n== TURN AMPLIFICATION (requests per user prompt, main) ==')
if turns:
    ns = sorted(t[1] for t in turns); cs = sorted(t[2] for t in turns)
    print(f'  prompts {len(turns)}  median req/prompt {st.median(ns)}  p90 {ns[int(.9 * len(ns))]}  max {ns[-1]}')
    print(f'  median cost/prompt {st.median(cs) / 1e3:.0f}K  p90 {cs[int(.9 * len(cs))] / 1e3:.0f}K  max {cs[-1] / 1e3:.0f}K  (=% of 5h: med {100 * st.median(cs) / 10e6:.1f} p90 {100 * cs[int(.9 * len(cs))] / 10e6:.1f})')
    big = [t for t in turns if t[1] >= 20]
    print(f'  prompts with >=20 requests: {len(big)} = {100 * sum(t[2] for t in big) / tc:.1f}% of cost')
print('\n== querySource (api-request records) ==', dict(qsrc.most_common()))
print('== multi-iteration requests ==', sum(1 for r in reqs if r['it'] > 1))
print('\n== ATTACHMENT TOKENS ADDED by type ==')
for k, v in att_types.most_common(15): print(f'  {k:28s} {v / 1e3:7.0f}K')
print('\n== WHAT-IF promptCacheTtl 5m (estimate [I]: writes 1.25 instead of 2, every gap >5 min rewrites the context) ==')
w5 = 0.0
for r in reqs:
    miss = (not r['first']) and r['gap'] is not None and r['gap'] > 300
    cw5 = r['cw'] + (r['cr'] if miss else 0); cr5 = 0 if miss else r['cr']
    w5 += r['i'] + 1.25 * cw5 + W['cr'] * cr5 + W['out'] * r['o']
print(f'  1h (now) {tc / 1e6:.1f}M  ->  5m {w5 / 1e6:.1f}M  ({100 * (w5 - tc) / tc:+.1f}%)  gaps >5 min: {sum(1 for r in reqs if r["gap"] and r["gap"] > 300)}')
print('\n== BY DAY ==')
for dday in sorted({r['day'] for r in reqs}):
    rs = [r for r in reqs if r['day'] == dday]
    print(f'  {dday} n={len(rs):5d} {sum(r["cost"] for r in rs) / 1e6:5.1f}M  eff={dict(collections.Counter(str(r["eff"]) for r in rs).most_common(2))}')
print('\n== BY PROJECT ==')
for pj, v in collections.Counter({p: sum(r['cost'] for r in reqs if r['proj'] == p) for p in {r['proj'] for r in reqs}}).most_common(8):
    print(f'  {pj:30s} {pc(v)}')
