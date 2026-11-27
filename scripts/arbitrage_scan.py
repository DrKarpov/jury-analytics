"""Bulk discovery and raw-tree verification for the same missing-buy pattern.
No per-address whitelist. Keep unverified candidates visible; never assume a quote.
"""
import argparse,time,json
from collections import Counter
from pathlib import Path
from functools import partial
from indexer import TOKEN,digest,integer,hash_id,publish
from provider import address,tonapi_request
from incremental import load_history
from arbitrage import candidate_pairs,evidence_records,verify
from discrepancy import tree_index
from recovery import read

def peer(x):
    return address(x['address'] if isinstance(x,dict) else x)
def raw_record(t,a,b,sell,tree,event):
    by_hash=tree_index(tree,t)
    root=by_hash[t];w,p,q=a['destination'],a['source'],b['destination']
    if event.get('event_id')!=t or event.get('in_progress') is not False:raise ValueError('event incomplete')
    def amt(n):return {'raw':str(integer(n))}
    txs=[]
    # TonAPI traces represent the internal message graph by parent-child links.
    # Build both endpoints from each child's actual in-message. Bind to parent
    # outgoing hash when present; reject inconsistent or missing internal outputs.
    stack=[(tree,None)]
    while stack:
        n,parent=stack.pop();x=n['transaction'];h=hash_id(x['hash']);account=peer(x['account'])
        stamp=integer(x['utime']);lt=str(integer(x['lt']))
        if x.get('success') is not True or x.get('aborted') is not False:raise ValueError('unsuccessful transaction')
        msgs=[]
        def msg(m,direction):
            if m.get('msg_type')!='int_msg' or m.get('bounced') is not False:raise ValueError('non-internal or bounced message')
            return {'direction':direction,'counterparty':peer(m['source' if direction=='in' else 'destination']),'amount_gram':amt(m['value']),'opcode':m.get('op_code'),'bounced':False}
        if parent is not None:
            m=x['in_msg'];px=parent['transaction']
            if peer(m['source'])!=peer(px['account']) or peer(m['destination'])!=account:raise ValueError('bad tree edge')
            msgs.append(msg(m,'in'))
        elif (x.get('in_msg') or {}).get('msg_type')=='int_msg':
            raise ValueError('root internal funding outside trace')
        children=n.get('children') or []
        child_hashes=set()
        for child in children:
            m=child['transaction']['in_msg']
            if peer(m['source'])!=account or peer(m['destination'])!=peer(child['transaction']['account']):raise ValueError('bad child endpoint')
            mh=hash_id(m['hash'])
            if mh in child_hashes:raise ValueError('duplicate message')
            child_hashes.add(mh);msgs.append(msg(m,'out'))
        if 'out_msgs' in x:
            declared={hash_id(m['hash']) for m in x['out_msgs'] if m.get('msg_type')=='int_msg'}
            # Some TonAPI trace responses omit already expanded outputs.
            if declared and declared!=child_hashes:raise ValueError('incomplete outgoing tree')
        txs.append({'hash':h,'account':account,'lt':lt,'time':stamp,'success':True,'fee_gram':amt(x['total_fees']),'messages':msgs})
        stack.extend((c,n) for c in children)
    actions=[]
    for x in event['actions']:
        typ=x['type']
        if typ=='JettonTransfer' and x['status']=='ok':
            d=x[typ]
            if peer(d['jetton']['address'])!=TOKEN:continue
            actions.append({'type':'jetton_transfer','status':'ok','action_name':typ,'sender':peer(d['sender']),'recipient':peer(d['recipient']),'jetton':{'master':TOKEN},'amount':amt(d['amount'])})
        elif typ=='JettonSwap' and x['status']=='ok':
            actions.append({'type':'other','status':'ok','action_name':typ})
    return {'version':1,'trace':t,'owner':w,'first':p,'second':q,'time':a['time'],
            'source':'TonAPI finalized trace tree and event, matched against Toncenter transfers',
            'root_message':{'event_id':t,'in_progress':False,'time':a['time'],'actions':actions},
            'transactions':txs}

def run(store,fetch=tonapi_request,seconds=180,limit=100):
    h=load_history(store);folder=store/'arbitrage'/'v1';verified=folder/'verified';verified.mkdir(parents=True,exist_ok=True)
    known={r['trace'] for r in evidence_records(store)}
    candidates=[]
    for t,rows in h.traces.items():
        for a,b,sell in candidate_pairs(rows,h.events.get(t,[])):
            candidates.append((t,a,b,sell))
    candidates.sort(key=lambda x:(x[1]['time'],x[0]))
    pending=folder/'attempts.json';old=read(pending) if pending.exists() else {}
    attempts=0;added=0;stop=None;deadline=time.monotonic()+seconds
    if fetch is tonapi_request:fetch=partial(fetch,deadline=deadline)
    for t,a,b,sell in candidates:
        if t in known or t in old:continue
        if attempts>=limit or time.monotonic()>=deadline:break
        attempts+=1
        try:
            tree=fetch('traces/'+t,{})
            event=fetch('events/'+t,{})
            r=raw_record(t,a,b,sell,tree,event)
            buy,cycle=verify(r,h.traces[t],h.events[t])
        except OSError as e:
            stop=type(e).__name__;break
        except (ValueError,KeyError,TypeError,AttributeError) as e:
            old[t]={'reason':type(e).__name__+': '+str(e)[:160],'at':int(time.time())}
            continue
        publish(r,verified/(t+'.json'));known.add(t);added+=1
        print('VERIFIED CYCLE',t,cycle['native_net_raw'],flush=True)
    publish(old,pending)
    report={'history_head':h.head,'cutoff':h.cutoff,'traces_examined':len(h.traces),
            'candidate_cycles':len(candidates),'verified_candidates':sum(t in known for t,*_ in candidates),
            'unverified_attempts':sum(t in old for t,*_ in candidates),
            'pending_candidates':sum(t not in known and t not in old for t,*_ in candidates),
            'added_this_run':added,'attempts_this_run':attempts,'stop_reason':stop,
            'candidate_sources':dict(Counter(a['source'] for t,a,b,e in candidates)),
            'failure_reasons':dict(Counter(x['reason'] for x in old.values())),
            'scope':'exact two-transfer missing-buy pattern only; additional route shapes still require analysis'}
    publish(report,folder/'status.json');print('ARBITRAGE CENSUS',json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--seconds',type=int,default=180);p.add_argument('--limit',type=int,default=100);a=p.parse_args();run(a.store,seconds=a.seconds,limit=a.limit)
