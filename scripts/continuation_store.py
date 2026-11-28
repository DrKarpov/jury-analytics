"""Persistent post-anchor shadow continuation; never a public accounting source.

Each immutable raw envelope extends a validated account prefix. A sampled
timestamp target and per-account provider tips are not global block finality.
"""
import argparse,json,time
from collections import Counter
from functools import partial
from pathlib import Path
from canonical_movements import Observations
from continuation_shadow import capture,replay,require
from genesis_checkpoint import ANCHOR,checked,signed,validate_master,validate_receipt
from indexer import digest,integer,publish
from provider import request,tonapi_request
from recovery import read
from wallet_history import graph,key,load_wallets

def cursor(base):
    require(base['complete'] and base['rows'],'historical account prefix incomplete')
    return {'prefix':{**base,'rows':list(base['rows'])},'target':ANCHOR,'tip_reached':True,
            'pending_tip':None,'pages':0,'last_observed_at':0,'new_rows':[]}

def apply(current,record,wallet,master_digest):
    target=integer(record['target'])
    require(target>=current['target'],'continuation target rollback')
    require(current['tip_reached'] or target==current['target'],'unfinished pinned target changed')
    rows,complete=replay(record,current['prefix'],master_digest,target,wallet)
    # Bind an unfinished page to its independently compared original tip.
    from wallet_history import compare
    raw=record['raw'];tip=compare(raw['tip_center']['transactions'][0],raw['tip_alternate']['transactions'][0],wallet)
    if not current['tip_reached']:
        require(tip==current['pending_tip'],'unfinished pinned tip changed')
        require(bool(rows),'unfinished continuation did not advance')
    require(target>current['target'] or not current['tip_reached'],'duplicate completed target')
    prior=current['prefix']['prior'] if not rows else (rows[-1]['lt'],rows[-1]['tx'],rows[-1]['state_after'])
    # "complete" in the shared replay interface describes the validated base
    # prefix, NOT whether the requested continuation target has been reached.
    prefix={**current['prefix'],'prior':prior,'head':record['digest'],
            'rows':current['prefix']['rows']+rows,'complete':True}
    return {'prefix':prefix,'target':target,'tip_reached':complete,'pending_tip':None if complete else tip,
            'pages':current['pages']+1,'new_rows':current['new_rows']+rows,
            'last_observed_at':integer(record['observed_at'])}

def load(folder,states,eligible,master_digest):
    cursors={}
    if not folder.exists():return cursors
    for d in sorted(folder.iterdir()):
        require(d.is_dir(),'unexpected continuation record path')
        wallet=d.name.replace('_',':',1)
        require(wallet in eligible and key(wallet)==d.name,'orphan continuation wallet')
        c=cursor(states[wallet])
        for n,path in enumerate(sorted(d.glob('*.json'))):
            require(path.name==f'page-{n:08d}.json','continuation page sequence gap')
            c=apply(c,read(path),wallet,master_digest)
        require(c['pages']>0,'empty continuation wallet folder')
        cursors[wallet]=c
    return cursors

def next_target(current,target):
    if not current['tip_reached']:return current['target']
    return target if target>current['target'] else None

def run(store,center=request,alternate=tonapi_request,limit=12,seconds=90):
    require(1<=limit<=30 and 1<=seconds<=180,'invalid continuation budget')
    g=store/'genesis'/'v1';master=read(g/'master.json');md=master['digest'];messages=validate_master(master)
    roots=set()
    for p in sorted((g/'receipts').glob('*.json')):
        q=validate_receipt(read(p),messages[p.stem],md)
        if integer(q['recipient_at'])<=ANCHOR:roots.add(q['wallet'])
    states=load_wallets(g/'wallet-history',md)
    linked,_,_,_=graph(states,roots)
    eligible={w for w in linked if states.get(w,{}).get('complete') and states[w]['rows']}
    target=integer(read(store/'update-status.json')['cutoff'])
    require(target>ANCHOR,'primary target has not passed anchor')
    folder=store/'continuation'/'v1';records=folder/'accounts'
    cursors=load(records,states,eligible,md)
    require(all(c['target']<=target for c in cursors.values()),'primary target rolled back')
    pending=folder/'pending.json'
    old=checked(read(pending)) if pending.exists() else {'master_digest':md,'anchor':ANCHOR,'failures':{}}
    require(old['master_digest']==md and old['anchor']==ANCHOR,'continuation pending identity mismatch')
    failures=dict(old['failures']);require(set(failures)<=eligible,'orphan continuation failure')
    now=int(time.time())
    def get(w):return cursors[w] if w in cursors else cursor(states[w])
    def priority(w):
        c=cursors.get(w)
        return (0 if c and not c['tip_reached'] else 1,
                max(c['last_observed_at'] if c else 0,failures.get(w,{}).get('at',0)),
                -sum(x['time']>=ANCHOR-86400 for x in states[w]['rows']),w)
    todo=sorted((w for w in eligible if (w not in cursors or next_target(cursors[w],target) is not None)
                 and now-failures.get(w,{}).get('at',0)>=600),key=priority)
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    attempted=written=new_count=0;stop=None
    for w in todo[:limit]:
        if time.monotonic()>=deadline:stop='budget';break
        attempted+=1;c=get(w);want=next_target(c,target)
        try:
            record,rows,complete=capture(w,c['prefix'],md,want,center,alternate)
            record=signed({**{k:v for k,v in record.items() if k!='digest'},'observed_at':int(time.time())})
            advanced=apply(c,record,w,md)
            require(len(advanced['new_rows'])-len(c['new_rows'])==len(rows) and advanced['tip_reached']==complete,'capture/replay mismatch')
        except OSError as e:
            failures[w]={'at':int(time.time()),'reason':type(e).__name__+': '+str(e)[:180]};stop=type(e).__name__;break
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            failures[w]={'at':int(time.time()),'reason':str(e)[:200]};continue
        dest=records/key(w)/f"page-{c['pages']:08d}.json"
        require(not dest.exists(),'immutable continuation page already exists')
        dest.parent.mkdir(parents=True,exist_ok=True);publish(record,dest)
        cursors[w]=advanced;written+=1;new_count+=len(rows);failures.pop(w,None)
    # Cold replay of all saved envelopes verifies durable cursors independently
    # of the just-completed fetch and catches torn/mutated checkpoints.
    restored=load(records,states,eligible,md)
    require(restored==cursors,'persistent continuation replay differs')
    base=Observations();base.ingest((w,x) for w,s in states.items() for x in s['rows'])
    before=base.project(roots)
    base.ingest((w,x) for w,c in restored.items() for x in c['new_rows'])
    combined=base.project(roots)
    old_events={x['id']:x for x in before['events']};new_events={x['id']:x for x in combined['events']}
    require(all(new_events.get(k)==v for k,v in old_events.items()),'historical movement changed')
    folder.mkdir(parents=True,exist_ok=True)
    publish(signed({'anchor':ANCHOR,'master_digest':md,'failures':failures}),pending)
    summary={'version':1,'anchor':ANCHOR,'master_digest':md,'target_timestamp':target,
        'eligible_accounts':len(eligible),'accounts_observed':len(restored),
        'accounts_reached_current_target':sum(c['tip_reached'] and c['target']==target for c in restored.values()),
        'accounts_with_unfinished_pages':sum(not c['tip_reached'] for c in restored.values()),
        'total_envelopes':sum(c['pages'] for c in restored.values()),
        'total_new_rows':sum(len(c['new_rows']) for c in restored.values()),
        'attempted_this_run':attempted,'envelopes_this_run':written,'new_rows_this_run':new_count,
        'pending_failure_accounts':len(failures),'failure_reasons':dict(Counter(x['reason'] for x in failures.values())),
        'base_matched_deliveries':len(old_events),'combined_matched_deliveries':len(new_events),
        'additional_matched_deliveries':len(new_events)-len(old_events),'projection_digest':digest(combined),
        'cold_replay_equal':True,'stop_reason':stop,
        'scope':'bounded persistent continuation for completed historical linked accounts; no independent new-wallet/master discovery or common finalized block boundary; shadow only'}
    publish(signed(summary),folder/'status.json')
    print('PERSISTENT CONTINUATION',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--limit',type=int,default=12);p.add_argument('--seconds',type=int,default=90);a=p.parse_args();run(a.store,limit=a.limit,seconds=a.seconds)
