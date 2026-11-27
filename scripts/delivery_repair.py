"""Recover only previously missed DEX legs with exact token delivery and independent agreement.
Not a net wallet or frontend attribution rule. Failed later legs remain unresolved.
"""
import argparse,json,time
from pathlib import Path
from indexer import classify,digest,publish,hash_id,integer
from provider import address,request,tonapi_request
from recovery import load_seed,read
from repair_overlay import contexts,overlay as alias_overlay
from payout_repair import overlay as payout_overlay,good,child,account,msg,nodes
from repair_alias import swaps
from discrepancy import category,multiset,tree_index
from incremental import load_history
from audit import tonapi_swaps
from indexer import fetch_actions

RULE='exact_swap_transfer_delivery_v1'
def match_delivery(a,endpoint,matches,qty,by_hash):
    # Keep the previous rule unless it actually had ambiguous matching transfers.
    if len(matches)<=1:return matches
    if a.get('details',{}).get('dex') not in ('stonfi_v2','dedust_v2'):return []
    src,dst=address(endpoint['source']),address(endpoint['destination'])
    sw,dw=address(endpoint['source_jetton_wallet']),address(endpoint['destination_jetton_wallet'])
    candidates=[]
    for r in matches:
        if r['source']!=src or r['destination']!=dst:continue
        try:
            n=by_hash[r['tx']];m=msg(n);b=m['decoded_body']
            if not good(n) or m.get('op_code')!='0x0f8a7ea5' or account(n)!=sw or address(m['source']['address'])!=src or address(b['destination'])!=dst or integer(b['amount'])!=qty:continue
            c=child(n,'0x178d4519',dw);cb=msg(c)['decoded_body']
            if integer(cb['query_id'])!=integer(b['query_id']) or integer(cb['amount'])!=qty or address(cb['from'])!=src:continue
            candidates.append(r)
        except (ValueError,KeyError,TypeError,AttributeError):continue
    return candidates

def propose(t,acts,rows,old,u,cutoff,alt,tree):
    try:
        tree_index(tree,t)
        order=lambda es:sorted(es,key=lambda e:e['id'])
        before,v=classify(t,acts,rows,cutoff,allow_alias=False)
        if order(before)!=order(old) or v!=u:return None
        n=nodes(tree)
        after,w=classify(t,acts,rows,cutoff,allow_alias=False,swap_matcher=lambda a,e,m,q:match_delivery(a,e,m,q,n))
        if len(after)<=len(old) or any(e not in after for e in old) or swaps(after)!=alt:return None
        return {'events':order(after),'unresolved':w,'added':len(after)-len(old)}
    except (ValueError,KeyError,TypeError,AttributeError):return None

def validate(r,seed,ctx):
    rows,events,unresolved,audit=ctx;t=r['trace']
    if r.get('version')!=1 or r.get('rule')!=RULE or r.get('seed_digest')!=seed['digest'] or r.get('digest')!=digest({k:v for k,v in r.items() if k!='digest'}):raise ValueError('invalid delivery repair')
    if t not in audit or category(audit[t])!='primary_missing':raise ValueError('wrong discrepancy')
    if r['before_events']!=events[t] or r['before_unresolved']!=unresolved.get(t) or r['transfer_digest']!=digest(sorted(rows[t],key=lambda r:r['tx'])):raise ValueError('delivery baseline changed')
    if any(hash_id(a['trace_id'])!=t for a in r['center_actions']) or len({hash_id(a['action_id']) for a in r['center_actions']})!=len(r['center_actions']):raise ValueError('invalid action identity')
    alt=tonapi_swaps(r['alternate_event'],t)
    if alt!=multiset(audit[t]['alternate_swaps']) or swaps(events[t])!=multiset(audit[t]['primary_swaps']):raise ValueError('delivery audit mismatch')
    p=propose(t,r['center_actions'],rows[t],events[t],unresolved.get(t),seed['cutoff'],alt,r['raw_trace'])
    if p is None or p!=r['proposal']:raise ValueError('delivery repair not reproducible')
    return p

def overlay(store,seed,h,ctx=None):
    paths=sorted((store/'repairs'/RULE).glob('*.json'))
    if paths and ctx is None:ctx=contexts(store,seed)
    active=set();stats={'validated':0,'active_resolutions':0,'added_events':0,'conflicts':0}
    used={e['id'] for es in h.events.values() for e in es}
    for path in paths:
        r=read(path);t=r['trace']
        if path.name!=t+'.json':raise ValueError('invalid filename')
        p=validate(r,seed,ctx);stats['validated']+=1
        current=sorted(h.events.get(t,[]),key=lambda e:e['id']);u=h.unresolved.get(t)
        if digest(sorted(h.traces.get(t,[]),key=lambda r:r['tx']))!=r['transfer_digest']:
            stats['conflicts']+=1;continue
        if current==p['events'] and u==p['unresolved']:
            active.add(t);continue
        if current!=sorted(r['before_events'],key=lambda e:e['id']) or u!=r['before_unresolved']:
            stats['conflicts']+=1;continue
        ids={e['id'] for e in p['events']};old={e['id'] for e in current}
        if len(ids)!=len(p['events']) or (ids-old)&used:raise ValueError('duplicate delivery repair')
        h.events[t]=p['events'];used.update(ids)
        if p['unresolved'] is None:h.unresolved.pop(t,None)
        else:h.unresolved[t]=p['unresolved']
        active.add(t);stats['added_events']+=p['added']
    stats['active_resolutions']=len(active);h.candidate()
    return stats,active

def run(store,center=request,alternate=tonapi_request,limit=15,seconds=120):
    seed=load_seed(store);ctx=contexts(store,seed);rows,events,unresolved,audit=ctx
    h=load_history(store,seed);alias_overlay(store,seed,h);payout_overlay(store,seed,h);overlay(store,seed,h,ctx)
    folder=store/'repairs'/RULE;folder.mkdir(parents=True,exist_ok=True)
    attempts=store/'repair-attempts'/RULE;attempts.mkdir(parents=True,exist_ok=True)
    deadline=time.monotonic()+seconds;examined=installed=0
    for t,a in sorted(audit.items()):
        if category(a)!='primary_missing' or (folder/(t+'.json')).exists() or (attempts/(t+'.json')).exists():continue
        if examined>=limit or time.monotonic()>=deadline:break
        if h.events.get(t,[])!=events[t] or h.unresolved.get(t)!=unresolved.get(t):continue
        examined+=1
        try:
            acts=fetch_actions(center,[t])[t];ev=alternate('events/'+t,{})
            alt=tonapi_swaps(ev,t)
            if alt!=multiset(a['alternate_swaps']):continue
            tree=alternate('traces/'+t,{});tree_index(tree,t)
        except (OSError,ValueError,KeyError,TypeError,AttributeError):break
        p=propose(t,acts,rows[t],events[t],unresolved.get(t),seed['cutoff'],alt,tree)
        if p is None:
            r={'version':1,'rule':RULE,'trace':t,'seed_digest':seed['digest'],'audit_digest':digest(a),'status':'no_rule_match'}
            r['digest']=digest(r);publish(r,attempts/(t+'.json'));continue
        r={'version':1,'rule':RULE,'trace':t,'seed_digest':seed['digest'],'before_events':events[t],'before_unresolved':unresolved.get(t),
           'transfer_digest':digest(sorted(rows[t],key=lambda r:r['tx'])),'center_actions':acts,'alternate_event':ev,'raw_trace':tree,'proposal':p}
        r['digest']=digest(r);validate(r,seed,ctx);publish(r,folder/(t+'.json'));installed+=1
        print('Verified exact delivery',t,p['added'],flush=True)
    h=load_history(store,seed);alias_overlay(store,seed,h);payout_overlay(store,seed,h);stats,active=overlay(store,seed,h,ctx)
    stats.update({'seed_digest':seed['digest'],'history_head':h.head,'examined_this_run':examined,'installed_this_run':installed})
    publish(stats,store/'delivery-status.json');print(json.dumps(stats),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);a=p.parse_args();run(a.store)
