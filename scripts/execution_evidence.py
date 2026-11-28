"""Exact execution evidence for unresolved token messages.

An aborted transfer request is not a token movement. This module establishes
execution observations only, not a jetton balance delta or refund.
"""
import json,time
from collections import Counter
from functools import partial
from continuation_shadow import require
from genesis_checkpoint import checked,signed
from indexer import TOKEN,hash_id,publish
from provider import request,tonapi_request,paired
from recovery import read
from wallet_history import compare,INTERNAL,successful

def inspect(raw,wallet,known):
    rows=raw['center']['transactions']
    require(len(rows)==1,'execution transaction not unique')
    c,a=rows[0],raw['alternate']
    row=compare(c,a,wallet)
    require(row==known,'execution observation differs from saved chain')
    inbound=row['in'];outs=row['out']
    aborted=row['aborted'] is True and row['alternate_success'] is False
    emitted=[m for m in outs if m['token_opcode']==INTERNAL and m['source']==wallet]
    burns=[m for m in outs if m['token_opcode'] in ('0x595f07bc','0x7bdd97de')]
    status='execution_requires_state_or_message_proof'
    if aborted and inbound and inbound['token_opcode']=='0x0f8a7ea5' and inbound['bounced'] is False and not emitted and not burns:
        status='aborted_transfer_request_no_observed_token_settlement'
    return {'tx':row['tx'],'wallet':wallet,'lt':str(row['lt']),'time':row['time'],
            'status':status,'aborted':row['aborted'],'alternate_success':row['alternate_success'],
            'inbound':inbound,'outbound':outs,'internal_outbound_count':len(emitted),
            'burn_outbound_count':len(burns),'state_before':row['state_before'],'state_after':row['state_after'],
            'code_before':row['code_before'],'code_after':row['code_after'],
            'state_hash_equal':row['state_before']==row['state_after'],
            'center_description':c.get('description'),'alternate_compute_phase':a.get('compute_phase'),
            'alternate_action_phase':a.get('action_phase'),'alternate_bounce_phase':a.get('bounce_phase'),
            'scope':'raw execution observation; no proven token-state delta, compensation or balance'}

def replay(record,known,md):
    checked(record)
    require(record['version']==1 and record['master_digest']==md,'execution evidence identity mismatch')
    require(known is not None and known[0]==record['wallet'],'execution original row absent')
    result=inspect(record['raw'],known[0],known[1])
    require(result==record['observation'],'execution replay mismatch')
    return result

def capture(folder,obs,plan,md,target,center=request,alternate=tonapi_request,limit=8,seconds=24):
    require(1<=limit<=20 and 0<seconds<=60,'invalid execution budget')
    dest=folder/'execution-observations';dest.mkdir(parents=True,exist_ok=True)
    saved={}
    for path in sorted(dest.glob('*.json')):
        require(hash_id(path.stem)==path.stem,'execution filename identity mismatch')
        record=read(path)
        require(record['tx']==path.stem,'execution record filename mismatch')
        saved[path.stem]=replay(record,obs.rows.get(path.stem),md)
    tasks=[t for t in plan['tasks'] if t['route']=='inspect_raw_execution_and_state']
    current={t['tx'] for t in tasks}
    require(None not in current and current<=set(obs.rows),'execution task lacks original row')
    old_count=len(saved)
    pending=folder/'execution-pending.json'
    old=checked(read(pending)) if pending.exists() else {'master_digest':md,'failures':{}}
    require(old['master_digest']==md,'execution pending identity mismatch')
    failures={k:v for k,v in old['failures'].items() if k in current and k not in saved}
    now=int(time.time())
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    todo=sorted((k for k in current-set(saved) if now-failures.get(k,{}).get('at',0)>=600),
                key=lambda k:(failures.get(k,{}).get('at',0),obs.rows[k][1]['lt'],k))
    attempts=0;stop=None
    for tx in todo[:limit]:
        if time.monotonic()>=deadline:stop='budget';break
        wallet,row=obs.rows[tx];lt=row['lt'];attempts+=1
        try:
            c,a=paired(lambda:center('transactions',{'account':wallet,'sort':'asc','limit':1,'start_lt':lt,'end_lt':lt}),
                       lambda:alternate('blockchain/transactions/'+tx,{}))
            raw={'center':c,'alternate':a}
            value=inspect(raw,wallet,row)
            record=signed({'version':1,'master_digest':md,'tx':tx,'wallet':wallet,'observed_at':int(time.time()),
                           'raw':raw,'observation':value})
            replay(record,(wallet,row),md)
        except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            failures[tx]={'at':int(time.time()),'reason':type(e).__name__+': '+str(e)[:180]}
            if isinstance(e,OSError) and getattr(e,'code',None)!=404:stop=type(e).__name__;break
            continue
        path=dest/(tx+'.json');require(not path.exists(),'execution observation already exists')
        publish(record,path);saved[tx]=value;failures.pop(tx,None)
    for tx,value in saved.items():
        require(replay(read(dest/(tx+'.json')),obs.rows.get(tx),md)==value,'execution cold replay differs')
    active=set(saved)&current
    for t in tasks:
        if t['tx'] in active:
            value=saved[t['tx']]
            msgs=[value['inbound']] if t['side']=='incoming' else value['outbound']
            require(any(m and m['hash']==t['message'] and m['token_opcode']==t['opcode'] and m['amount_raw']==t['amount_raw'] for m in msgs),
                    'execution task message mismatch')
    result={'version':1,'master_digest':md,'target_timestamp':target,'candidate_transactions':len(current),
            'candidate_message_observations':len(tasks),'current_verified_transactions':len(active),
            'current_verified_message_observations':sum(t['tx'] in active for t in tasks),
            'persisted_transactions':len(saved),'new_records':len(saved)-old_count,'replayed_records':old_count,
            'execution_status_counts':dict(Counter(saved[k]['status'] for k in active)),
            'unresolved_transactions':len(current-active),'pending_failures':len(failures),
            'failure_reasons':dict(Counter(v['reason'] for v in failures.values())),
            'attempts':attempts,'stop_reason':stop,'cold_replay_equal':True,
            'scope':'execution observations only; no ledger postings changed, no state delta or refund inferred'}
    publish(signed({'master_digest':md,'failures':failures}),pending)
    return result
