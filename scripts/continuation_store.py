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
from wallet_history import graph,key,load_wallets,successful,valid_internal

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

def select_accounts(eligible,states,cursors,failures,target,now,limit):
    # Separate discovery from refresh: a growing historical frontier must
    # never monopolize every slot while already-observed wallets become stale.
    def priority(w):
        c=cursors.get(w)
        return (0 if c and not c['tip_reached'] else 1,
                max(c['last_observed_at'] if c else 0,failures.get(w,{}).get('at',0)),
                -sum(x['time']>=ANCHOR-86400 for x in states[w]['rows']),w)
    todo=sorted((w for w in eligible if (w not in cursors or next_target(cursors[w],target) is not None)
                 and now-failures.get(w,{}).get('at',0)>=600),key=priority)
    refresh=[w for w in todo if w in cursors]
    discovery=[w for w in todo if w not in cursors]
    # For a one-slot budget alternate by total successfully stored envelopes.
    if limit==1:
        first,second=(discovery,refresh) if sum(c['pages'] for c in cursors.values())%2==0 else (refresh,discovery)
        return (first or second)[:1]
    selected=[]
    for i in range(max(len(refresh),len(discovery))):
        if i<len(refresh):selected.append(refresh[i])
        if i<len(discovery):selected.append(discovery[i])
        if len(selected)>=limit:break
    return selected[:limit]

def post_anchor_frontier(states,cursors,roots):
    # The graph is the same verifier used by the canonical projection.
    # A previously unseen peer is a discovery candidate, NOT a verified JURY
    # wallet or proof of when that account was deployed.
    combined={w:{'rows':s['rows']+cursors.get(w,{}).get('new_rows',[])} for w,s in states.items()}
    linked,_,_,matched=graph(combined,roots)
    _,historical_candidates,_,_=graph(states,roots)
    edges=[]
    for w in sorted(linked):
        for row in combined.get(w,{}).get('rows',[]):
            if row['time']<=ANCHOR or not successful(row):continue
            for side,msgs,direction,peer in (('outgoing',row['out'],'source','destination'),
                                             ('incoming',[row['in']],'destination','source')):
                for m in msgs:
                    if not valid_internal(m,w,direction) or m['hash'] in matched:continue
                    other=m[peer]
                    state=('has_continuation_cursor' if other in cursors else
                           'historical_prefix_complete' if states.get(other,{}).get('complete') else
                           'historical_candidate' if other in historical_candidates else 'not_in_historical_graph')
                    edges.append({'side':side,'message':m['hash'],'wallet':w,'peer':other,'peer_state':state,
                                  'transaction':row['tx'],'lt':str(row['lt']),'time':row['time'],'amount_raw':m['amount_raw']})
    edges.sort(key=lambda e:(e['side'],e['message']))
    require(len({(e['side'],e['message']) for e in edges})==len(edges),'duplicate post-anchor frontier edge')
    return {'edges':edges,'unmatched_post_anchor_outgoing':sum(e['side']=='outgoing' for e in edges),
            'unmatched_post_anchor_incoming':sum(e['side']=='incoming' for e in edges),
            'frontier_peer_accounts':len({e['peer'] for e in edges}),
            'peers_not_in_historical_graph':len({e['peer'] for e in edges if e['peer_state']=='not_in_historical_graph'}),
            'edges_by_peer_state':dict(Counter(e['peer_state'] for e in edges))}

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
    todo=select_accounts(eligible,states,cursors,failures,target,now,limit)
    previous_envelopes=sum(c['pages'] for c in cursors.values())
    previously_observed=set(cursors)
    previous_projection=Observations()
    previous_projection.ingest((w,x) for w,s in states.items() for x in s['rows'])
    previous_projection.ingest((w,x) for w,c in cursors.items() for x in c['new_rows'])
    previous_events={x['id']:x for x in previous_projection.project(roots)['events']}
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    attempted=written=new_count=resumed=resumed_rows=0;stop=None
    for w in todo:
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
        if w in previously_observed:resumed+=1;resumed_rows+=len(rows)
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
    require(all(new_events.get(k)==v for k,v in previous_events.items()),'previous continuation movement changed')
    frontier=post_anchor_frontier(states,restored,roots)
    folder.mkdir(parents=True,exist_ok=True)
    publish(signed({'anchor':ANCHOR,'master_digest':md,'failures':failures}),pending)
    frontier_record=signed({'version':1,'anchor':ANCHOR,'master_digest':md,'target_timestamp':target,
                            'projection_digest':digest(combined),**frontier,
                            'scope':'unpaired post-anchor messages in sampled account chains; peers are candidates, not verified new wallets'})
    publish(frontier_record,folder/'frontier.json')
    summary={'version':1,'anchor':ANCHOR,'master_digest':md,'target_timestamp':target,
        'eligible_accounts':len(eligible),'accounts_observed':len(restored),
        'accounts_reached_current_target':sum(c['tip_reached'] and c['target']==target for c in restored.values()),
        'accounts_with_unfinished_pages':sum(not c['tip_reached'] for c in restored.values()),
        'total_envelopes':sum(c['pages'] for c in restored.values()),
        'total_new_rows':sum(len(c['new_rows']) for c in restored.values()),
        'attempted_this_run':attempted,'envelopes_this_run':written,'new_rows_this_run':new_count,
        'replayed_previous_envelopes':previous_envelopes,'resumed_accounts_this_run':resumed,
        'resumed_rows_this_run':resumed_rows,'new_accounts_this_run':written-resumed,
        'oldest_account_completed_target':min((c['target'] if c['tip_reached'] else ANCHOR for c in restored.values()),default=ANCHOR),
        'frontier_digest':frontier_record['digest'],**{k:v for k,v in frontier.items() if k!='edges'},
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
