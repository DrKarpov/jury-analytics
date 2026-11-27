"""Resume bounded alias repairs from saved independent seed audit checkpoints."""
import argparse,json,time
from collections import Counter
from pathlib import Path
from indexer import digest,publish,fetch_actions
from recovery import load_seed,load_progress,read
from repair_alias import propose
from repair_overlay import RULE,contexts,verify,overlay
from discrepancy import category,multiset
from incremental import load_history
from audit import tonapi_swaps
from provider import request,tonapi_request

def checked_attempt(path,seed,trace,audit_row):
    a=read(path)
    if a.get('version')!=1 or a.get('rule')!=RULE or a.get('seed_digest')!=seed['digest'] or a.get('trace')!=trace or a.get('audit_digest')!=digest(audit_row):
        raise ValueError('repair attempt identity mismatch')
    if a.get('digest')!=digest({k:v for k,v in a.items() if k!='digest'}):
        raise ValueError('repair attempt checksum mismatch')
    if a.get('status') not in ('no_rule_match','alternate_changed','history_changed'):
        raise ValueError('invalid repair attempt status')
    return a

def run(store,center=request,alternate=tonapi_request,limit=40,seconds=100,seed=None):
    if not 1<=limit<=100 or seconds<=0:raise ValueError('invalid repair budget')
    seed=load_seed(store) if seed is None else seed
    ctx=contexts(store,seed);rows,events,unresolved,audit=ctx
    history=load_history(store,seed)
    folder=store/'repairs'/RULE;folder.mkdir(parents=True,exist_ok=True)
    attempts=store/'repair-attempts'/RULE;attempts.mkdir(parents=True,exist_ok=True)
    # Validate all installed evidence before attempting new repairs.
    initial=overlay(store,seed,history)
    pending=[]
    for t,a in sorted(audit.items()):
        if (folder/(t+'.json')).exists():continue
        if (attempts/(t+'.json')).exists():
            checked_attempt(attempts/(t+'.json'),seed,t,a);continue
        if t in unresolved:pending.append(t)
    deadline=time.monotonic()+seconds
    examined=installed=0;stop=None
    def bounded(fetch):
        def get(e,p):
            if time.monotonic()>=deadline:raise TimeoutError('repair time budget exhausted')
            return fetch(e,p)
        return get
    cf,af=bounded(center),bounded(alternate)
    def record(t,status,actions=None,alt=None):
        a={'version':1,'rule':RULE,'seed_digest':seed['digest'],'trace':t,
           'audit_digest':digest(audit[t]),'status':status}
        if actions is not None:a['center_actions']=actions
        if alt is not None:a['alternate_event']=alt
        a['digest']=digest(a);publish(a,attempts/(t+'.json'))
    for i in range(0,min(len(pending),limit),20):
        if time.monotonic()>=deadline:break
        group=pending[i:i+20]
        try:actions=fetch_actions(cf,group)
        except OSError as e:stop=type(e).__name__;break
        for t in group:
            if time.monotonic()>=deadline:break
            examined+=1
            order=lambda es:sorted(es,key=lambda e:e['id'])
            if order(history.events.get(t,[]))!=order(events[t]) or history.unresolved.get(t)!=unresolved[t] or digest(sorted(history.traces.get(t,[]),key=lambda r:r['tx']))!=digest(sorted(rows[t],key=lambda r:r['tx'])):
                record(t,'history_changed');continue
            wanted=multiset(audit[t]['alternate_swaps'])
            result=propose(t,actions[t],rows[t],events[t],unresolved[t],seed['cutoff'],wanted)
            if result is None:
                record(t,'no_rule_match',actions[t]);continue
            try:ev=af('events/'+t,{});actual=tonapi_swaps(ev,t)
            except OSError as e:stop=type(e).__name__;break
            except (ValueError,KeyError,TypeError,AttributeError) as e:
                # Invalid/unfinished provider response is retryable, not a negative result.
                stop=type(e).__name__;break
            if actual!=wanted:
                record(t,'alternate_changed',actions[t],ev);continue
            rec={'version':1,'rule':RULE,'seed_digest':seed['digest'],'trace':t,
                 'before_events':events[t],'before_unresolved':unresolved[t],
                 'transfer_digest':digest(sorted(rows[t],key=lambda r:r['tx'])),
                 'center_actions':actions[t],'alternate_event':ev,'proposal':result}
            rec['digest']=digest(rec);verify(rec,seed,ctx)
            publish(rec,folder/(t+'.json'));installed+=1
            print('Auto-reconciled',t,result['added'],flush=True)
        if stop:break
    # Rebuild from immutable history to detect cross-record conflicts.
    history=load_history(store,seed);result=overlay(store,seed,history)
    from payout_repair import overlay as payout_overlay
    payouts,payout_active=payout_overlay(store,seed,history,ctx)
    queue=[]
    for t,a in sorted(audit.items()):
        if t in payout_active:continue
        if (folder/(t+'.json')).exists():
            r=read(folder/(t+'.json'))
            same=digest(sorted(history.traces.get(t,[]),key=lambda r:r['tx']))==r['transfer_digest']
            active=same and sorted(history.events.get(t,[]),key=lambda e:e['id'])==r['proposal']['events'] and history.unresolved.get(t)==r['proposal']['unresolved']
            if active:continue
            status='repair_conflict'
        elif (attempts/(t+'.json')).exists():
            status=checked_attempt(attempts/(t+'.json'),seed,t,a)['status']
        else:status='pending_alias_check' if t in unresolved else 'other_rule_required'
        queue.append({'trace':t,'category':category(a),'status':status})
    ids,cursor,counts=load_progress(store,seed)
    if len(queue)!=counts['mismatch']-result['active_resolutions']-payouts['active_resolutions']:
        raise ValueError('repair queue coverage mismatch')
    q={'seed_digest':seed['digest'],'history_head':history.head,'audit_attempted':cursor,
       'remaining':len(queue),'by_category':dict(Counter(r['category'] for r in queue)),
       'by_status':dict(Counter(r['status'] for r in queue)),'rows':queue}
    q['digest']=digest(q);publish(q,store/'repair-queue.json')
    status={'seed_digest':seed['digest'],'history_head':history.head,**result,
            'examined_this_run':examined,'installed_this_run':installed,
            'payout_resolutions':payouts['active_resolutions'],'remaining_mismatches':len(queue),'pending_alias_checks':q['by_status'].get('pending_alias_check',0),
            'seed_audit_attempted':cursor,'seed_audit_unavailable':counts['unavailable'],
            'stop_reason':stop}
    publish(status,store/'repair-status.json');print(json.dumps(status),flush=True)
    return status

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--limit',type=int,default=40);p.add_argument('--seconds',type=int,default=100);a=p.parse_args()
    run(a.store,limit=a.limit,seconds=a.seconds)
