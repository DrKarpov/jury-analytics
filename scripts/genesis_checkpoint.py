"""Persistent, pinned master-chain and recipient evidence. Does not modify the beta seed."""
import argparse, time
from functools import partial
from pathlib import Path
from collections import Counter
from indexer import MASTER, TOKEN, digest, hash_id, integer, publish
from master_history import scan, receipt
from incremental import load_history
from recovery import read
from provider import address, request, tonapi_request

ANCHOR=1795796649
DEPLOYMENT='b6d564b65ad5b8aeb80821f30752da3d03393e2991a5c9ae269419a04a728481'
DEPLOYMENT_LT=117446032000001

def signed(body):
    return {**body,'digest':digest(body)}

def checked(record):
    if record.get('digest')!=digest({k:v for k,v in record.items() if k!='digest'}):
        raise ValueError('genesis record digest mismatch')
    return record

def validate_master(record):
    checked(record)
    if record.get('version')!=1 or record.get('token')!=MASTER or record.get('cutoff')!=ANCHOR:
        raise ValueError('wrong genesis anchor')
    rows=record['transactions']
    if not rows or rows[0]['tx']!=DEPLOYMENT or rows[0]['lt']!=DEPLOYMENT_LT or rows[0]['before']!='nonexist' or rows[0]['after']!='active' or rows[0]['aborted'] is not False:
        raise ValueError('wrong deployment')
    previous=(0,None); ids=set(); messages={}
    for row in rows:
        lt=integer(row['lt']); tx=hash_id(row['tx'])
        if tx!=row['tx'] or tx in ids or lt<=previous[0] or (row['previous_lt'],row['previous_tx'])!=previous or not 0<row['time']<=ANCHOR or type(row['aborted']) is not bool:
            raise ValueError('broken master chain')
        ids.add(tx);previous=(lt,tx)
        for msg in row['outbound']:
            key=msg['message']
            if hash_id(key)!=key or key in messages or address(msg['wallet'])!=msg['wallet'] or integer(msg['amount_raw'])<=0:
                raise ValueError('invalid master message')
            messages[key]={**msg,'master_tx':tx,'master_lt':lt,'master_at':row['time'],'master_aborted':row['aborted']}
    return messages

def capture_receipt(center,alternate,msg,master_digest):
    raw={}
    def c(e,p):
        raw['center']=center(e,p);return raw['center']
    def a(e,p):
        raw['alternate']=alternate(e,p);return raw['alternate']
    core={k:msg[k] for k in ('message','wallet','amount_raw')}
    proof=receipt(c,a,core)
    if integer(proof['recipient_lt'])<=msg['master_lt'] or integer(proof['recipient_at'])<msg['master_at']:
        raise ValueError('recipient precedes master')
    return signed({'version':1,'master_digest':master_digest,'message':msg,'proof':proof,'raw':raw})

def validate_receipt(record,msg,master_digest):
    checked(record)
    if record.get('version')!=1 or record.get('master_digest')!=master_digest or record.get('message')!=msg or msg['master_aborted']:
        raise ValueError('wrong receipt identity')
    raw=record['raw'];core={k:msg[k] for k in ('message','wallet','amount_raw')}
    replay=receipt(lambda e,p:raw['center'],lambda e,p:raw['alternate'],core)
    if replay!=record['proof'] or integer(replay['recipient_lt'])<=msg['master_lt'] or integer(replay['recipient_at'])<msg['master_at']:
        raise ValueError('receipt replay mismatch')
    return replay

def initialize(store,center,alternate):
    folder=store/'genesis'/'v1';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'master.json'
    if path.exists():
        record=read(path);validate_master(record);return record
    h=load_history(store)
    if h.cutoff<ANCHOR:raise ValueError('primary history has not reached genesis anchor')
    rows=scan(center,alternate,ANCHOR)
    record=signed({'version':1,'token':MASTER,'cutoff':ANCHOR,'transactions':rows,
                   'scope':'two-provider predecessor chain and outbound messages at pinned account tip, not block proof'})
    messages=validate_master(record)
    publish(record,path)
    print('Pinned master:',len(rows),'transactions;',len(messages),'outbound messages',flush=True)
    return record

def advance(store,center,alternate,limit=60,seconds=200):
    if not 1<=limit<=100 or seconds<=0:raise ValueError('invalid receipt budget')
    folder=store/'genesis'/'v1';master=read(folder/'master.json')
    all_messages=validate_master(master)
    messages={k:v for k,v in all_messages.items() if not v['master_aborted']}
    dest=folder/'receipts';dest.mkdir(exist_ok=True)
    verified={}
    for path in sorted(dest.glob('*.json')):
        key=path.stem
        if key not in messages:raise ValueError('orphan receipt')
        verified[key]=validate_receipt(read(path),messages[key],master['digest'])
    failures_path=folder/'pending.json'
    old=read(failures_path) if failures_path.exists() else {'master_digest':master['digest'],'failures':{}}
    if old['master_digest']!=master['digest']:raise ValueError('pending anchor mismatch')
    failures=old['failures']
    if not set(failures)<=set(messages):raise ValueError('orphan pending entry')
    for key in verified:failures.pop(key,None)
    pending=sorted(set(messages)-set(verified),key=lambda k:(failures.get(k,{}).get('attempted_at',0),messages[k]['master_lt'],k))
    deadline=time.monotonic()+seconds; attempted=0;new=0;stop=None
    for key in pending[:limit]:
        if time.monotonic()>=deadline:break
        attempted+=1
        try:
            record=capture_receipt(center,alternate,messages[key],master['digest'])
        except OSError as e:
            stop=type(e).__name__;break
        except (ValueError,KeyError,TypeError,AttributeError) as e:
            failures[key]={'attempted_at':int(time.time()),'reason':type(e).__name__+': '+str(e)[:180]}
            continue
        proof=validate_receipt(record,messages[key],master['digest'])
        publish(record,dest/(key+'.json'))
        verified[key]=proof;failures.pop(key,None);new+=1
        if new%10==0:print('Verified receipts:',len(verified),'/',len(messages),flush=True)
    publish({'master_digest':master['digest'],'failures':failures},failures_path)
    amounts=lambda rows:str(sum(integer(x['amount_raw']) for x in rows))
    status={'version':1,'master_digest':master['digest'],'cutoff':ANCHOR,
            'master_transactions':len(master['transactions']),'outbound_messages':len(messages),
            'outbound_amount_raw':amounts(messages.values()),'verified_receipts':len(verified),
            'verified_amount_raw':amounts(verified.values()),'verified_wallets':len({v['wallet'] for v in verified.values()}),
            'pending_receipts':len(messages)-len(verified),'failed_attempts_unresolved':len(failures),
            'receipts_after_cutoff':sum(integer(v['recipient_at'])>ANCHOR for v in verified.values()),
            'attempted_this_run':attempted,'new_receipts':new,'stop_reason':stop,
            'scope':'master outbound and independently compared recipient transactions only; not full wallet history or balance proof'}
    publish(signed(status),folder/'status.json');print(status,flush=True)
    return status

def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['master','receipts']);p.add_argument('--store',type=Path,required=True);p.add_argument('--limit',type=int,default=60);p.add_argument('--seconds',type=int,default=200);a=p.parse_args()
    deadline=time.monotonic()+a.seconds
    c=partial(request,deadline=deadline);t=partial(tonapi_request,deadline=deadline)
    if a.stage=='master':initialize(a.store,c,t)
    else:advance(a.store,c,t,a.limit,a.seconds)

if __name__=='__main__':main()
