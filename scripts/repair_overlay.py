"""Immutable, independently checked alias repair overlay. Never rewrite seed or update segments."""
import argparse,json
from collections import defaultdict
from pathlib import Path
from indexer import digest,publish,hash_id
from recovery import load_seed,load_progress,read
from repair_alias import propose,swaps
from discrepancy import multiset
from audit import tonapi_swaps
from incremental import load_history

RULE='legacy_dedust_jury_unsigned_workchain'

def contexts(store,seed):
    load_progress(store,seed)
    rows=defaultdict(list);events=defaultdict(list)
    for r in seed['transfers']:rows[r['trace']].append(r)
    for e in seed['events']:events[e['trace']].append(e)
    unresolved={u['trace']:u for u in seed['unresolved']}
    audit={}
    for p in sorted((store/'audit').glob('batch-*.json')):
        for r in read(p)['rows']:
            if r['status']=='mismatch':audit[r['trace']]=r
    return rows,events,unresolved,audit

def verify(record,seed,ctx):
    if record.get('version')!=1 or record.get('rule')!=RULE or record.get('seed_digest')!=seed['digest']:
        raise ValueError('repair identity mismatch')
    if record.get('digest')!=digest({k:v for k,v in record.items() if k!='digest'}):
        raise ValueError('repair digest mismatch')
    t=record['trace'];rows,events,unresolved,audit=ctx
    if hash_id(t)!=t or t not in audit or t not in unresolved:raise ValueError('repair has no original discrepancy')
    if record['before_events']!=events[t] or record['before_unresolved']!=unresolved[t]:
        raise ValueError('repair baseline mismatch')
    if record['transfer_digest']!=digest(sorted(rows[t],key=lambda r:r['tx'])):
        raise ValueError('repair transfer evidence mismatch')
    a=audit[t]
    if swaps(events[t])!=multiset(a['primary_swaps']):raise ValueError('audit baseline mismatch')
    alt=tonapi_swaps(record['alternate_event'],t)
    if alt!=multiset(a['alternate_swaps']):raise ValueError('alternate observation changed')
    acts=record['center_actions']
    if any(hash_id(x['trace_id'])!=t for x in acts) or len({hash_id(x['action_id']) for x in acts})!=len(acts):
        raise ValueError('wrong or repeated action')
    proposal=propose(t,acts,rows[t],events[t],unresolved[t],seed['cutoff'],alt)
    if proposal is None or proposal!=record['proposal']:raise ValueError('repair cannot be reproduced')
    return proposal

def overlay(store,seed,h):
    paths=sorted((store/'repairs'/RULE).glob('*.json'))
    ctx=contexts(store,seed) if paths else None
    report={'validated':0,'applied':0,'already_present':0,'conflicts':0,'added_events':0,'active_resolutions':0}
    used={e['id'] for es in h.events.values() for e in es}
    hashes=[]
    for path in paths:
        r=read(path);t=r['trace']
        if path.name!=t+'.json':raise ValueError('repair filename mismatch')
        proposal=verify(r,seed,ctx)
        hashes.append(r['digest']);report['validated']+=1
        order=lambda es:sorted(es,key=lambda e:e['id'])
        current=order(h.events.get(t,[]));u=h.unresolved.get(t)
        if digest(sorted(h.traces.get(t,[]),key=lambda r:r['tx']))!=r['transfer_digest']:
            report['conflicts']+=1;continue
        if current==proposal['events'] and u==proposal['unresolved']:
            report['already_present']+=1;report['active_resolutions']+=1;continue
        if current!=order(r['before_events']) or u!=r['before_unresolved']:
            report['conflicts']+=1;continue
        old_ids={e['id'] for e in current};new_ids={e['id'] for e in proposal['events']}
        if len(new_ids)!=len(proposal['events']) or (new_ids-old_ids)&used:raise ValueError('duplicate repaired event')
        h.events[t]=proposal['events'];used.update(new_ids)
        if proposal['unresolved'] is None:h.unresolved.pop(t,None)
        else:h.unresolved[t]=proposal['unresolved']
        report['applied']+=1;report['active_resolutions']+=1;report['added_events']+=proposal['added']
    report['repair_digest']=digest(hashes)
    h.candidate()
    return report

def install(src,store,expected_count):
    seed=load_seed(store);ctx=contexts(store,seed)
    paths=sorted(p for p in src.glob('*.json') if p.name!='report.json')
    report=read(src/'report.json')
    if report['seed_digest']!=seed['digest'] or report['proposed']!=len(paths) or len(paths)!=expected_count or report['errors']!=0:
        raise ValueError('unexpected repair artifact')
    records=[]
    for p in paths:
        r=read(p)
        if p.name!=r['trace']+'.json':raise ValueError('artifact filename mismatch')
        verify(r,seed,ctx);records.append(r)
    if sum(r['proposal']['added'] for r in records)!=report['added']:raise ValueError('repair count mismatch')
    folder=store/'repairs'/RULE;folder.mkdir(parents=True,exist_ok=True)
    for r in records:
        p=folder/(r['trace']+'.json')
        if p.exists() and read(p)!=r:raise ValueError('immutable repair conflict')
    for r in records:
        p=folder/(r['trace']+'.json')
        if not p.exists():publish(r,p)
    h=load_history(store,seed);result=overlay(store,seed,h)
    if result['conflicts']:raise ValueError('current history conflicts with repair; inspect before committing')
    publish({'seed_digest':seed['digest'],'history_head':h.head,**result},store/'repair-status.json')
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--expected-count',type=int,required=True);a=p.parse_args()
    install(a.input,a.store,a.expected_count)
