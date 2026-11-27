"""Publisher provenance for trace revisions, not an independent blockchain proof."""
from collections import defaultdict
from incremental import History
from indexer import digest
from recovery import read

def state(h,t):
    return {'transfers':sorted(h.traces.get(t,[]),key=lambda r:r['tx']),
            'events':sorted(h.events.get(t,[]),key=lambda e:e['id']),
            'unresolved':h.unresolved.get(t)}

def lineage(store,seed,corrected):
    h=History(seed);heads=[{'digest':h.head,'cutoff':h.cutoff}];edges=defaultdict(list)
    def record(t,before,after,kind,source):
        a,b=digest(before),digest(after)
        if a!=b:edges[t].append({'from':a,'to':b,'kind':kind,'source':source,'head':h.head})
    for path in sorted((store/'updates').glob('batch-*.json')):
        b=read(path);ts={r['trace'] for r in b['patches']};before={t:state(h,t) for t in ts}
        h.apply(b);heads.append({'digest':h.head,'cutoff':h.cutoff})
        for t in sorted(ts):record(t,before[t],state(h,t),'update',h.head)
    if corrected.head!=h.head or corrected.cutoff!=h.cutoff or corrected.transfers!=h.transfers:
        raise ValueError('corrected history not bound to primary chain')
    proofs=defaultdict(list)
    for path in sorted((store/'repairs').glob('*/*.json')):
        r=read(path)
        if r['digest']!=digest({k:v for k,v in r.items() if k!='digest'}):raise ValueError('repair checksum mismatch')
        proofs[r['trace']].append(r['digest'])
    for t in sorted(h.traces):
        a,b=state(h,t),state(corrected,t)
        if a!=b:
            if len(proofs[t])!=1:raise ValueError('missing or ambiguous repair provenance')
            record(t,a,b,'repair',proofs[t][0])
    return {'version':1,'seed_digest':seed['digest'],'heads':heads,'transitions':dict(edges),
            'scope':'publisher-validated update and repair provenance; not independent proof or signature'}
