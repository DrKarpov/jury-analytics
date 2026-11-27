"""Narrow DeDust v2 -> Omniston referral sale settlement reconciliation.
The received message value is not net wallet profit or a gas-adjusted amount.
"""
import argparse,json,time
from collections import Counter
from pathlib import Path
from functools import partial
from repair_attempt import checked_negative_attempt
from indexer import classify,digest,publish,hash_id,integer
from provider import address,request,tonapi_request
from recovery import load_seed,read,load_progress
from repair_overlay import contexts,overlay as alias_overlay
from repair_alias import swaps
from discrepancy import category,multiset,tree_index
from incremental import load_history
from audit import tonapi_swaps
from indexer import fetch_actions

RULE='dedust_v2_omniston_final_native_payout_v1'
REFERRAL='0:f0e5e2ebc4b9e4166c3641f49ac8972343890fd8a756e3649cde04a208a85acb'

def account(n):return address(n['transaction']['account']['address'])
def msg(n):return n['transaction']['in_msg']
def good(n):
    t=n['transaction'];m=msg(n)
    return t['success'] is True and t['aborted'] is False and m['bounced'] is False and m['msg_type']=='int_msg' and address(m['destination']['address'])==account(n)

def child(n,op,dest=None):
    matches=[]
    for c in n.get('children',[]):
        m=msg(c)
        if m.get('op_code','').lower()!=op:continue
        if dest is not None and account(c)!=dest:continue
        if address(m['source']['address'])!=account(n) or not good(c):raise ValueError('invalid child message')
        if not integer(n['transaction']['lt'])<integer(m['created_lt'])<integer(c['transaction']['lt']):raise ValueError('message order')
        matches.append(c)
    if len(matches)!=1:raise ValueError('ambiguous message route')
    return matches[0]

def nodes(tree):
    result={};stack=[tree]
    while stack:
        n=stack.pop();result[hash_id(n['transaction']['hash'])]=n
        stack.extend(n.get('children',[]))
    return result

def payout(e,a,row,by_hash):
    d=a['details'];i,o=d['dex_incoming_transfer'],d['dex_outgoing_transfer']
    owner=e['wallet'];pool=address(i['destination'])
    if e['kind']!='sell' or e['quote_asset']!='GRAM' or d.get('dex')!='dedust_v2' or d.get('peer_swaps'):
        raise ValueError('unsupported venue or route')
    if address(i['source'])!=owner or address(o['source'])!=pool or address(o['destination'])!=REFERRAL or o['asset'] is not None:
        raise ValueError('unexpected endpoint')
    n=by_hash[row['tx']]
    if not good(n) or msg(n).get('op_code')!='0x0f8a7ea5' or address(msg(n)['source']['address'])!=owner:
        raise ValueError('invalid input transfer')
    if account(n)!=address(i['source_jetton_wallet']) or row['source']!=owner or row['destination']!=pool:
        raise ValueError('wrong token wallet')
    b=msg(n)['decoded_body'];q=integer(e['amount_raw']);qid=integer(b['query_id'])
    if integer(b['amount'])!=q or address(b['destination'])!=pool or row['amount_raw']!=e['amount_raw']:
        raise ValueError('transfer amount mismatch')
    internal=child(n,'0x178d4519',address(i['destination_jetton_wallet']))
    notify=child(internal,'0x7362d09c',pool)
    for step,key in ((internal,'from'),(notify,'sender')):
        body=msg(step)['decoded_body']
        if integer(body['query_id'])!=qid or integer(body['amount'])!=q or address(body[key])!=owner:
            raise ValueError('token flow mismatch')
    if not any(x in notify.get('interfaces',[]) for x in ('dedust_v2_cpmm','dedust_v2_stableswap')):
        raise ValueError('unknown pool interface')
    referral=child(notify,'0x3216ca09',REFERRAL)
    if 'omniston_referral' not in referral.get('interfaces',[]):raise ValueError('unknown referral interface')
    # Explicit payout opcode, not an excess/refund or a sum of arbitrary native messages.
    final=child(referral,'0x4cb700a9',owner)
    amount=integer(msg(final)['value'])
    if amount<=0:raise ValueError('zero payout')
    return str(amount),[hash_id(x['transaction']['hash']) for x in (n,internal,notify,referral,final)]

def propose(trace,actions,rows,old,unresolved,cutoff,alt,tree):
    try:
        tree_index(tree,trace)
        before,u=classify(trace,actions,rows,cutoff,allow_alias=False)
        order=lambda es:sorted(es,key=lambda e:e['id'])
        if order(before)!=order(old) or u!=unresolved:return None
        by_hash=nodes(tree);by_tx={r['tx']:r for r in rows};by_id={hash_id(a['action_id']):a for a in actions}
        if len(by_id)!=len(actions) or any(hash_id(a['trace_id'])!=trace for a in actions):return None
        out=[];proof=[]
        for e in old:
            if e['kind']=='sell' and e['quote_asset']=='GRAM' and e.get('venue')=='dedust_v2':
                key=('sell',e['wallet'],integer(e['amount_raw']),'GRAM',integer(e['quote_raw']))
                if alt[key]==0:
                    value,route=payout(e,by_id[e['id']],by_tx[e['transfer_tx']],by_hash)
                    if value==e['quote_raw']:return None
                    proof.append({'event':e['id'],'original_quote_raw':e['quote_raw'],'received_raw':value,'route':route})
                    e={**e,'quote_raw':value}
            out.append(e)
        if not proof or swaps(out)!=alt or len({p['route'][-1] for p in proof})!=len(proof):return None
        return {'events':order(out),'unresolved':unresolved,'changed_quotes':len(proof),'proof':proof}
    except (ValueError,KeyError,TypeError,AttributeError):return None

def validate(r,seed,ctx):
    rows,events,unresolved,audit=ctx;t=r['trace']
    if r.get('rule')!=RULE or r.get('seed_digest')!=seed['digest'] or r.get('version')!=1 or r.get('digest')!=digest({k:v for k,v in r.items() if k!='digest'}):
        raise ValueError('invalid payout evidence')
    if t not in audit or category(audit[t])!='quote_difference':raise ValueError('wrong discrepancy')
    if r['before_events']!=events[t] or r['before_unresolved']!=unresolved.get(t) or r['transfer_digest']!=digest(sorted(rows[t],key=lambda r:r['tx'])):
        raise ValueError('payout baseline mismatch')
    alt=tonapi_swaps(r['alternate_event'],t)
    if alt!=multiset(audit[t]['alternate_swaps']) or swaps(events[t])!=multiset(audit[t]['primary_swaps']):
        raise ValueError('audit mismatch')
    p=propose(t,r['center_actions'],rows[t],events[t],unresolved.get(t),seed['cutoff'],alt,r['raw_trace'])
    if p is None or p!=r['proposal']:raise ValueError('payout not reproducible')
    return p

def overlay(store,seed,h,ctx=None):
    paths=sorted((store/'repairs'/RULE).glob('*.json'))
    if paths and ctx is None:ctx=contexts(store,seed)
    result={'active_resolutions':0,'changed_quotes':0,'conflicts':0,'validated':0}
    active=set()
    for path in paths:
        r=read(path);t=r['trace']
        if path.name!=t+'.json':raise ValueError('wrong filename')
        p=validate(r,seed,ctx);result['validated']+=1
        order=lambda es:sorted(es,key=lambda e:e['id'])
        current=order(h.events.get(t,[]))
        if digest(sorted(h.traces.get(t,[]),key=lambda r:r['tx']))!=r['transfer_digest'] or h.unresolved.get(t)!=r['before_unresolved'] or current not in (order(r['before_events']),p['events']):
            result['conflicts']+=1;continue
        h.events[t]=p['events'];active.add(t)
        result['active_resolutions']+=1;result['changed_quotes']+=p['changed_quotes']
    h.candidate()
    return result,active

def run(store,center=request,alternate=tonapi_request,limit=15,seconds=100,seed=None):
    if not 1<=limit<=100 or seconds<=0:raise ValueError('invalid repair budget')
    seed=load_seed(store) if seed is None else seed;ctx=contexts(store,seed)
    rows,events,unresolved,audit=ctx
    h=load_history(store,seed);alias_overlay(store,seed,h);overlay(store,seed,h,ctx)
    folder=store/'repairs'/RULE;folder.mkdir(parents=True,exist_ok=True)
    attempted=store/'repair-attempts'/RULE;attempted.mkdir(parents=True,exist_ok=True)
    examined=installed=0;deadline=time.monotonic()+seconds
    if center is request:
        center = partial(request, deadline=deadline)
    if alternate is tonapi_request:
        alternate = partial(tonapi_request, deadline=deadline)
    for t,a in sorted(audit.items()):
        if category(a)!='quote_difference' or (folder/(t+'.json')).exists():continue
        attempt=attempted/(t+'.json')
        if attempt.exists():
            checked_negative_attempt(attempt,seed['digest'],t,RULE,a)
            continue
        if examined>=limit or time.monotonic()>=deadline:break
        examined+=1
        if sorted(h.events.get(t,[]),key=lambda e:e['id'])!=sorted(events[t],key=lambda e:e['id']):continue
        try:
            acts=fetch_actions(center,[t])[t];ev=alternate('events/'+t,{})
            alt=tonapi_swaps(ev,t)
            if alt!=multiset(a['alternate_swaps']):continue
            tree=alternate('traces/'+t,{})
            tree_index(tree,t)
        except (OSError,ValueError,KeyError,TypeError):break
        p=propose(t,acts,rows[t],events[t],unresolved.get(t),seed['cutoff'],alt,tree)
        if p is None:
            x={'rule':RULE,'seed_digest':seed['digest'],'trace':t,'audit_digest':digest(a),'status':'no_rule_match'}
            x['digest']=digest(x);publish(x,attempted/(t+'.json'));continue
        r={'version':1,'rule':RULE,'seed_digest':seed['digest'],'trace':t,'before_events':events[t],
           'before_unresolved':unresolved.get(t),'transfer_digest':digest(sorted(rows[t],key=lambda r:r['tx'])),
           'center_actions':acts,'alternate_event':ev,'raw_trace':tree,'proposal':p}
        r['digest']=digest(r);validate(r,seed,ctx);publish(r,folder/(t+'.json'));installed+=1
        print('Verified final payout',t,p['changed_quotes'],flush=True)
    result,active=overlay(store,seed,h,ctx)
    result.update({'seed_digest':seed['digest'],'history_head':h.head,'examined_this_run':examined,'installed_this_run':installed})
    publish(result,store/'payout-status.json');print(json.dumps(result),flush=True)
    return result,active

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=15)
    parser.add_argument('--seconds', type=int, default=100)
    args = parser.parse_args()
    run(args.store, limit=args.limit, seconds=args.seconds)
