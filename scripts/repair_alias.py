"""Conservative, independently compared repair proposals for the immutable seed."""
import argparse,time,json
from collections import Counter,defaultdict
from pathlib import Path
from indexer import classify,fetch_actions,digest,publish,integer
from recovery import load_seed,load_progress,read
from audit import tonapi_swaps
from discrepancy import multiset
from provider import request,tonapi_request

def swaps(events):
    return Counter((e['kind'],e['wallet'],integer(e['amount_raw']),e['quote_asset'],integer(e['quote_raw']))
                   for e in events if e['kind'] in ('buy','sell'))

def propose(trace,actions,rows,old,old_unresolved,cutoff,alternate):
    before,u=classify(trace,actions,rows,cutoff,allow_alias=False)
    after,v=classify(trace,actions,rows,cutoff)
    order=lambda es:sorted(es,key=lambda e:e['id'])
    if order(before)!=order(old) or u!=old_unresolved:return None
    if len(after)<=len(before) or any(e not in after for e in before):return None
    if swaps(after)!=alternate:return None
    return {'events':order(after),'unresolved':v,'added':len(after)-len(before)}

def investigate(store,out,center=request,alternate=tonapi_request):
    seed=load_seed(store);load_progress(store,seed)
    rows=defaultdict(list);old=defaultdict(list)
    unresolved={u['trace']:u for u in seed['unresolved']}
    for r in seed['transfers']:rows[r['trace']].append(r)
    for e in seed['events']:old[e['trace']].append(e)
    mismatches=[]
    for p in sorted((store/'audit').glob('batch-*.json')):
        for r in read(p)['rows']:
            if r['status']=='mismatch' and r['trace'] in unresolved:mismatches.append(r)
    # Batch primary action fetches; only re-query independent events for actual repair candidates.
    out.mkdir(parents=True,exist_ok=True)
    report={'seed_digest':seed['digest'],'eligible':len(mismatches),'examined':0,'proposed':0,'added':0,'errors':0,
            'scope':'repair proposals only; original history and published data unchanged'}
    deadline=time.monotonic()+360
    for i in range(0,min(len(mismatches),100),20):
        if time.monotonic()>=deadline:break
        group=mismatches[i:i+20];actions=fetch_actions(center,[r['trace'] for r in group])
        for row in group:
            if time.monotonic()>=deadline:break
            t=row['trace'];report['examined']+=1
            if swaps(old[t])!=multiset(row['primary_swaps']):raise ValueError('audit seed mismatch')
            wanted=multiset(row['alternate_swaps'])
            result=propose(t,actions[t],rows[t],old[t],unresolved[t],seed['cutoff'],wanted)
            if result is None:continue
            try:
                event=alternate('events/'+t,{})
                if tonapi_swaps(event,t)!=wanted:continue
            except (ValueError,KeyError,TypeError,OSError):
                report['errors']+=1;continue
            evidence={'version':1,'rule':'legacy_dedust_jury_unsigned_workchain','seed_digest':seed['digest'],
                      'trace':t,'before_events':old[t],'before_unresolved':unresolved[t],
                      'transfer_digest':digest(sorted(rows[t],key=lambda r:r['tx'])),
                      'center_actions':actions[t],'alternate_event':event,'proposal':result}
            evidence['digest']=digest(evidence);publish(evidence,out/(t+'.json'))
            report['proposed']+=1;report['added']+=result['added']
            print('Proposed',t,result['added'],flush=True)
    publish(report,out/'report.json');print(json.dumps(report),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    investigate(a.store,a.out)
