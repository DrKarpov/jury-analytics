"""Read-only post-anchor account continuation using the shared historical comparator.

Raw envelopes are replayable. Bounded sample and timestamp cap are NOT a global
finalized block cursor, complete live discovery or historical owner proof.
"""
import argparse,json,time
from collections import Counter
from functools import partial
from pathlib import Path
from canonical_movements import Observations
from genesis_checkpoint import ANCHOR,checked,signed,validate_master,validate_receipt
from indexer import digest,integer,publish
from provider import request,tonapi_request,paired
from recovery import read
from wallet_history import compare,check_rows,graph,load_wallets

def require(ok,reason):
    if not ok:raise ValueError(reason)

def replay(record,state,master_digest,target,wallet):
    checked(record)
    require(record['version']==1 and record['master_digest']==master_digest and record['wallet']==wallet
            and record['anchor']==ANCHOR and record['target']==target and record['base_head']==state['head']
            and tuple(record['prior'])==state['prior'] and state['complete'],'continuation checkpoint identity mismatch')
    require(target>ANCHOR,'continuation target must follow anchor')
    raw=record['raw'];c,a=raw['tip_center']['transactions'],raw['tip_alternate']['transactions']
    require(len(c)==len(a)==1,'nonunique continuation tip')
    tiprow=compare(c[0],a[0],wallet)
    tip={'tx':tiprow['tx'],'lt':tiprow['lt'],'time':tiprow['time']}
    prior=state['prior']
    require(0<tip['time']<=target and tip['lt']>=prior[0],'continuation tip outside scope or rollback')
    if tip['lt']==prior[0]:
        require(tiprow==state['rows'][-1] and raw.get('page_center') is None and raw.get('page_alternate') is None,
                'unchanged tip differs from saved row')
        return [],True
    require(tip['time']>ANCHOR,'new tip at or before anchor; historical gap')
    c,a=raw['page_center']['transactions'],raw['page_alternate']['transactions']
    require(0<len(c)==len(a)<=record['page_size'],'continuation page missing or unequal')
    rows=[compare(x,y,wallet) for x,y in zip(c,a,strict=True)]
    require(all(ANCHOR<x['time']<=target for x in rows),'post-anchor page contains historical gap')
    end=check_rows(rows,prior,tip,cutoff=target)
    if end[0]==tip['lt']:require(rows[-1]==tiprow,'continuation page differs from pinned tip')
    return rows,end[0]==tip['lt']

def capture(wallet,state,master_digest,target,center,alternate,size=100):
    endpoint=f'blockchain/accounts/{wallet}/transactions'
    c=center('transactions',{'account':wallet,'sort':'desc','limit':1,'end_utime':target})
    require(len(c['transactions'])==1,'no unique continuation tip')
    lt=integer(c['transactions'][0]['lt'])
    a=alternate(endpoint,{'sort_order':'desc','limit':1,'before_lt':lt+1})
    raw={'tip_center':c,'tip_alternate':a,'page_center':None,'page_alternate':None}
    prior=state['prior']
    if lt>prior[0]:
        c,a=paired(lambda:center('transactions',{'account':wallet,'sort':'asc','limit':size,'start_lt':prior[0]+1,'end_lt':lt}),
                   lambda:alternate(endpoint,{'sort_order':'asc','limit':size,'after_lt':prior[0],'before_lt':lt+1}))
        raw.update(page_center=c,page_alternate=a)
    record=signed({'version':1,'anchor':ANCHOR,'target':target,'master_digest':master_digest,'wallet':wallet,
                   'base_head':state['head'],'prior':list(prior),'page_size':size,'raw':raw})
    rows,complete=replay(record,state,master_digest,target,wallet)
    return record,rows,complete

def run(store,out,center=request,alternate=tonapi_request,limit=12,seconds=105):
    require(1<=limit<=30 and 1<=seconds<=180,'invalid continuation sample budget')
    g=store/'genesis'/'v1';master=read(g/'master.json');messages=validate_master(master)
    roots=set()
    for path in sorted((g/'receipts').glob('*.json')):
        q=validate_receipt(read(path),messages[path.stem],master['digest'])
        if integer(q['recipient_at'])<=ANCHOR:roots.add(q['wallet'])
    folder=g/'wallet-history';states=load_wallets(folder,master['digest'])
    status=checked(read(folder/'status.json'))
    require(status['master_digest']==master['digest'] and status['cutoff']==ANCHOR,'wrong historical checkpoint')
    target=integer(read(store/'update-status.json')['cutoff'])
    require(target>ANCHOR,'primary discovery has not passed anchor')
    linked,_,_,_=graph(states,roots)
    eligible=[w for w in linked if states.get(w,{}).get('complete') and states[w]['rows']]
    # Nonrepresentative sample: actively transacting completed chains first.
    eligible.sort(key=lambda w:(-sum(x['time']>=ANCHOR-86400 for x in states[w]['rows']),-states[w]['prior'][0],w))
    items=[(w,x) for w,s in states.items() for x in s['rows']]
    base=Observations();base.ingest(items);before=base.project(roots)
    require(len(items)==status['transactions_scanned'] and before['matched_deliveries']==status['matched_internal_messages'],'base projection mismatch')
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    records=[];failures=[];new=[];stop=None
    for w in eligible[:limit]:
        if time.monotonic()>=deadline:stop='budget';break
        try:
            record,rows,complete=capture(w,states[w],master['digest'],target,center,alternate)
        except OSError as e:
            failures.append({'wallet':w,'reason':type(e).__name__+': '+str(e)[:200]});stop=type(e).__name__;break
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            failures.append({'wallet':w,'reason':str(e)[:200]});continue
        records.append({'record':record,'rows':len(rows),'tip_reached':complete})
        new.extend((w,x) for x in rows)
    base.ingest(new);after=base.project(roots)
    # Rebuild from the exact raw envelopes, in opposite order with retries.
    rebuilt=Observations()
    for entry in reversed(records):
        record=entry['record'];w=record['wallet'];rows,complete=replay(record,states[w],master['digest'],target,w)
        require(len(rows)==entry['rows'] and complete==entry['tip_reached'],'raw envelope replay differs')
        batch=[(w,x) for x in reversed(rows)]
        rebuilt.ingest(batch);rebuilt.ingest(batch)
    rebuilt.ingest(reversed(items))
    require(after==rebuilt.project(roots),'post-anchor arrival/replay parity mismatch')
    previous={x['id']:x for x in before['events']};now={x['id']:x for x in after['events']}
    require(all(now.get(k)==v for k,v in previous.items()),'historical movement changed')
    added=[x for k,x in now.items() if k not in previous]
    summary={'anchor':ANCHOR,'target_timestamp':target,'master_digest':master['digest'],'base_status_digest':status['digest'],
             'eligible_complete_accounts':len(eligible),'attempted':len(records)+len(failures),
             'captured_accounts':len(records),'advanced_accounts':sum(x['rows']>0 for x in records),
             'tip_reached_accounts':sum(x['tip_reached'] for x in records),'new_rows':len(new),
             'post_anchor_rows_with_primary_mc_seqno':sum(x['mc_seqno']>0 for _,x in new),
             'base_deliveries':len(previous),'combined_deliveries':len(now),'added_matched_deliveries':len(added),
             'replay_parity':True,'failures':len(failures),'failure_reasons':dict(Counter(x['reason'] for x in failures)),
             'stop_reason':stop,'projection_digest':digest(after),
             'scope':'bounded post-anchor account sample, primary finalized rows and alternate agreement; not global block finality, independent full discovery, ledger or production live ingestion'}
    out.parent.mkdir(parents=True,exist_ok=True)
    publish(signed({**summary,'records':records,'failure_details':failures,'added_deliveries':added}),out)
    print('CONTINUATION SHADOW',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--limit',type=int,default=12);a=p.parse_args();run(a.store,a.out,limit=a.limit)
