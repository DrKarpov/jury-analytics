"""Targeted counterpart capture for the post-anchor shadow frontier.

Both ends must agree on exact internal message and LT order. A captured
counterpart is evidence for discovery, not an account prefix or wallet balance.
"""
import argparse,base64,json,time
from collections import Counter
from functools import partial
from pathlib import Path
from continuation_shadow import require
from continuation_store import load,post_anchor_frontier
from genesis_checkpoint import ANCHOR,checked,signed,validate_master,validate_receipt
from indexer import digest,hash_id,integer,publish
from provider import request,tonapi_request,paired
from recovery import read
from wallet_history import compare,graph,load_wallets,successful,valid_internal

def edge_message(row,side,mid,wallet):
    require(side in ('incoming','outgoing'),'invalid edge side')
    messages=[row['in']] if side=='incoming' else row['out']
    matches=[m for m in messages if m and m['hash']==mid]
    require(len(matches)==1,'message not uniquely observed')
    m=matches[0]
    require(successful(row) and valid_internal(m,wallet,'destination' if side=='incoming' else 'source'),
            'unsuccessful or invalid endpoint')
    return m

def counterpart(edge,known,raw,target):
    mid=edge['message'];side=edge['side'];wallet=edge['wallet'];peer=edge['peer']
    require(known['tx']==edge['transaction'] and known['lt']==integer(edge['lt'])
            and known['time']==edge['time'] and ANCHOR<known['time']<=target,'known endpoint identity mismatch')
    m=edge_message(known,side,mid,wallet)
    require(m['source' if side=='incoming' else 'destination']==peer and m['amount_raw']==edge['amount_raw'],
            'frontier message identity mismatch')
    rows=raw['center']['transactions']
    require(len(rows)==1,'counterpart not unique')
    other=compare(rows[0],raw['alternate'],peer)
    opposite='outgoing' if side=='incoming' else 'incoming'
    n=edge_message(other,opposite,mid,peer)
    require(m==n,'counterpart message mismatch')
    require(0<other['time']<=target,'counterpart outside observation target')
    require(other['lt']<known['lt'] if side=='incoming' else known['lt']<other['lt'],'counterpart LT order mismatch')
    return other

def fetch(edge,center,alternate):
    mid=edge['message'];encoded=base64.b64encode(bytes.fromhex(mid)).decode('ascii')
    direction='out' if edge['side']=='incoming' else 'in'
    params={'msg_hash':encoded,'direction':direction,'limit':2}
    if direction=='in':
        c,a=paired(lambda:center('transactionsByMessage',params),
                   lambda:alternate(f'blockchain/messages/{mid}/transaction',{}))
    else:
        c=center('transactionsByMessage',params)
        require(len(c['transactions'])==1,'counterpart sender not unique')
        tx=hash_id(c['transactions'][0]['hash'])
        a=alternate(f'blockchain/transactions/{tx}',{})
    return {'center':c,'alternate':a}

def record_key(edge):
    require(edge['side'] in ('incoming','outgoing') and hash_id(edge['message'])==edge['message'],'invalid frontier identity')
    return edge['side']+'-'+edge['message']

def validate(record,known,master_digest):
    checked(record)
    require(record['version']==1 and record['anchor']==ANCHOR and record['master_digest']==master_digest,'counterpart record identity mismatch')
    edge=record['edge']
    require(known is not None and known[0]==edge['wallet'],'counterpart original endpoint absent')
    other=counterpart(edge,known[1],record['raw'],record['target'])
    require(other==record['counterpart'],'counterpart replay differs')
    return other

def run(store,center=request,alternate=tonapi_request,limit=20,seconds=80):
    require(1<=limit<=40 and 1<=seconds<=180,'invalid counterpart budget')
    g=store/'genesis'/'v1';master=read(g/'master.json');md=master['digest'];messages=validate_master(master)
    roots=set()
    for path in sorted((g/'receipts').glob('*.json')):
        q=validate_receipt(read(path),messages[path.stem],md)
        if integer(q['recipient_at'])<=ANCHOR:roots.add(q['wallet'])
    states=load_wallets(g/'wallet-history',md)
    linked,_,_,_=graph(states,roots)
    eligible={w for w in linked if states.get(w,{}).get('complete') and states[w]['rows']}
    folder=store/'continuation'/'v1';status=checked(read(folder/'status.json'))
    frontier=checked(read(folder/'frontier.json'));target=status['target_timestamp']
    require(status['master_digest']==frontier['master_digest']==md and status['anchor']==frontier['anchor']==ANCHOR
            and status['frontier_digest']==frontier['digest'] and target==frontier['target_timestamp'],
            'frontier checkpoint identity mismatch')
    cursors=load(folder/'accounts',states,eligible,md)
    rebuilt=post_anchor_frontier(states,cursors,roots)
    require(all(frontier[k]==v for k,v in rebuilt.items()),'frontier replay mismatch')
    known={r['tx']:(w,r) for w,s in states.items() for r in s['rows']}
    known.update({r['tx']:(w,r) for w,c in cursors.items() for r in c['new_rows']})
    dest=folder/'counterparts';dest.mkdir(exist_ok=True)
    records={}
    for path in sorted(dest.glob('*.json')):
        rec=read(path);edge=rec['edge'];k=record_key(edge)
        require(path.stem==k,'counterpart filename mismatch')
        validate(rec,known.get(edge['transaction']),md)
        records[k]=rec
    old_count=len(records)
    active={record_key(e):e for e in frontier['edges']}
    pending=folder/'counterpart-pending.json'
    old=checked(read(pending)) if pending.exists() else {'master_digest':md,'anchor':ANCHOR,'failures':{}}
    require(old['master_digest']==md and old['anchor']==ANCHOR,'counterpart pending identity mismatch')
    failures={k:v for k,v in old['failures'].items() if k in active and k not in records}
    now=int(time.time())
    # Prefer previously unseen peers, then alternate receipt/sender lookups.
    todo=[e for k,e in active.items() if k not in records and now-failures.get(k,{}).get('at',0)>=600]
    todo.sort(key=lambda e:(e['peer_state']!='not_in_historical_graph',failures.get(record_key(e),{}).get('at',0),e['time'],e['message']))
    lanes=[[e for e in todo if e['side']==side] for side in ('outgoing','incoming')]
    ordered=[]
    for i in range(max(map(len,lanes),default=0)):
        for lane in lanes:
            if i<len(lane):ordered.append(lane[i])
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    attempted=0;stop=None
    for e in ordered[:limit]:
        if time.monotonic()>=deadline:stop='budget';break
        k=record_key(e);attempted+=1
        try:
            raw=fetch(e,center,alternate)
            other=counterpart(e,known[e['transaction']][1],raw,target)
            rec=signed({'version':1,'anchor':ANCHOR,'master_digest':md,'target':target,
                        'edge':e,'raw':raw,'counterpart':other,'observed_at':int(time.time())})
            validate(rec,known.get(e['transaction']),md)
        except OSError as error:
            failures[k]={'at':int(time.time()),'reason':type(error).__name__+': '+str(error)[:180]}
            # An individual missing message is not a global transport outage.
            if getattr(error,'code',None)==404:continue
            stop=type(error).__name__;break
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as error:
            failures[k]={'at':int(time.time()),'reason':str(error)[:200]};continue
        path=dest/(k+'.json')
        require(not path.exists(),'immutable counterpart already exists')
        publish(rec,path);records[k]=rec;failures.pop(k,None)
    # Revalidate all persisted observations. Do not inject isolated rows into
    # account-chain cursors or the canonical ledger until prefix continuity.
    for k,rec in records.items():
        saved=read(dest/(k+'.json'))
        require(saved==rec,'counterpart persistence mismatch')
        validate(saved,known.get(rec['edge']['transaction']),md)
    confirmed=set(active)&set(records)
    new_peers={active[k]['peer'] for k in confirmed if active[k]['peer_state']=='not_in_historical_graph'}
    summary={'version':1,'anchor':ANCHOR,'master_digest':md,'target_timestamp':target,
             'frontier_digest':frontier['digest'],'frontier_edges':len(active),
             'replayed_records':old_count,'persisted_records':len(records),'new_records':len(records)-old_count,
             'attempted_this_run':attempted,'confirmed_current_frontier_edges':len(confirmed),
             'confirmed_by_side':dict(Counter(active[k]['side'] for k in confirmed)),
             'confirmed_peer_accounts':len({active[k]['peer'] for k in confirmed}),
             'confirmed_peers_absent_from_historical_graph':len(new_peers),
             'remaining_current_frontier_edges':len(active)-len(confirmed),
             'pending_failure_edges':len(failures),'failure_reasons':dict(Counter(x['reason'] for x in failures.values())),
             'stop_reason':stop,'scope':'exact isolated two-provider counterpart observations; no wallet prefix, owner, balance, global discovery or public trade proof'}
    publish(signed({'anchor':ANCHOR,'master_digest':md,'failures':failures}),pending)
    publish(signed(summary),folder/'counterpart-status.json')
    print('COUNTERPART DISCOVERY',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--limit',type=int,default=20);p.add_argument('--seconds',type=int,default=80);a=p.parse_args();run(a.store,limit=a.limit,seconds=a.seconds)
