"""Bounded candidate census and independently replayable historical liquidity evidence."""
import argparse,time
from pathlib import Path
from collections import Counter
from functools import partial
from indexer import digest,publish,fetch_actions
from provider import request,tonapi_request
from recovery import read
from persistent_preview import corrected_history
from liquidity_proof import inspect,verify,fetch_pools

LP_TYPES={'dex_deposit_liquidity','dex_withdraw_liquidity'}
def fp(rows):return digest(sorted(rows,key=lambda r:r['tx']))
def seal(r):return {**r,'digest':digest(r)}
def checked(r):
    if r.get('digest')!=digest({k:v for k,v in r.items() if k!='digest'}):raise ValueError('invalid liquidity record digest')
    return r
def run(store,center=request,alternate=tonapi_request,seconds=170,limit=100,profile_limit=240):
    h,*_=corrected_history(store);folder=store/'liquidity-proof'/'v1';folder.mkdir(parents=True,exist_ok=True)
    records=folder/'records';records.mkdir(exist_ok=True)
    pp=folder/'profiles.json';ap=folder/'attempts.json'
    profiles=checked(read(pp))['profiles'] if pp.exists() else {}
    attempts=checked(read(ap))['attempts'] if ap.exists() else {}
    seed=read(store/'seed'/'liquidity.json')
    hints={r['trace'] for r in seed['events']+seed['unresolved']} & set(h.traces)
    fps={t:fp(rows) for t,rows in h.traces.items()}
    known={};counts=Counter();conflicts=0
    for path in sorted(records.glob('*.json')):
        rec=checked(read(path));t=rec['trace']
        if path.stem!=t:raise ValueError('liquidity filename mismatch')
        if fps.get(t)!=rec['fingerprint']:continue
        if verify(t,h.traces[t],rec['raw_trace'],rec['pool_transactions'])!=rec['results']:raise ValueError('liquidity proof replay mismatch')
        known[t]=rec
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    todo=sorted((t for t in h.traces if profiles.get(t,{}).get('fingerprint')!=fps[t] or time.time()-profiles[t]['at']>86400),
                key=lambda t:(t not in hints,profiles.get(t,{}).get('at',0),t not in h.unresolved,t))
    profiled=attempted=added=0;stop=None
    for i in range(0,min(len(todo),profile_limit),20):
        if time.monotonic()>=deadline-60:break
        group=todo[i:min(i+20,profile_limit)]
        try:actions=fetch_actions(center,group)
        except (OSError,ValueError,KeyError,TypeError) as e:stop=type(e).__name__;break
        for t in group:
            a=actions[t]
            profiles[t]={'fingerprint':fps[t],'hint':any(x.get('type') in LP_TYPES for x in a),'empty':not a,'at':int(time.time())}
            profiled+=1
    candidates=hints|{t for t,p in profiles.items() if p['hint'] and fps.get(t)==p['fingerprint']}
    eligible=sorted((t for t in candidates if t not in known and
                    (attempts.get(t,{}).get('fingerprint')!=fps[t] or time.time()-attempts[t]['at']>=3600)),
                    key=lambda t:(attempts.get(t,{}).get('at',0),t not in hints,t))
    for t in eligible:
        if attempted>=limit or time.monotonic()>=deadline:break
        attempted+=1
        try:
            tree=alternate('traces/'+t,{})
            g,cb=inspect(tree,t);pool=fetch_pools(center,g,cb)
            result=verify(t,h.traces[t],tree,pool)
            if not result:raise ValueError('no supported same-trace liquidity settlement')
        except OSError as e:stop=type(e).__name__;break
        except (ValueError,KeyError,TypeError,AttributeError) as e:
            attempts[t]={'fingerprint':fps[t],'at':int(time.time()),'reason':type(e).__name__+': '+str(e)[:200]};continue
        rec=seal({'version':1,'trace':t,'fingerprint':fps[t],'raw_trace':tree,'pool_transactions':pool,'results':result})
        publish(rec,records/(t+'.json'));known[t]=rec;attempts.pop(t,None);added+=1
    legs=set()
    for t,rec in known.items():
        existing={e['transfer_tx'] for e in h.events.get(t,[])}
        for r in rec['results']:
            counts[r['kind']]+=1
            for leg in r['legs']:
                legs.add(leg['tx'])
                if leg['tx'] in existing:conflicts+=1
    publish(seal({'version':1,'profiles':profiles}),pp);publish(seal({'version':1,'attempts':attempts}),ap)
    report={'version':1,'history_head':h.head,'cutoff':h.cutoff,'total_indexed_traces':len(h.traces),
            'profiled_current':sum(p['fingerprint']==fps.get(t) for t,p in profiles.items()),
            'profiled_this_run':profiled,'known_seed_lp_traces':len(hints),'candidate_traces':len(candidates),
            'confirmed_traces':len(known),'confirmed_operations':dict(counts),'confirmed_transfer_rows':len(legs),
            'overlap_with_existing_classification':conflicts,'added_this_run':added,'attempted_this_run':attempted,
            'pending_or_unverified':len(candidates-set(known)),
            'failure_reasons':dict(Counter(a['reason'] for t,a in attempts.items() if t in candidates and t not in known and a['fingerprint']==fps[t])),
            'stop_reason':stop,'scope':'provider-hinted traces only; historical code and causal liquidity-associated deliveries, not principal, fees, cross-trace LP or integrated trade metrics'}
    publish(seal(report),folder/'status.json');print('LIQUIDITY PROOF',report,flush=True)
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--seconds',type=int,default=170);a=p.parse_args();run(a.store,seconds=a.seconds)
