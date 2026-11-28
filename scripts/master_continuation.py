"""Independent persistent master continuation, using the shared account comparator.

Legacy master checkpoint lacks state hashes. Bind its last row to raw exact
transaction evidence before extending it. No supply or economic labels inferred.
"""
import argparse,json,time
from collections import Counter
from functools import partial
from pathlib import Path
from continuation_shadow import capture,require
from continuation_store import cursor,apply,next_target
from genesis_checkpoint import ANCHOR,checked,signed,validate_master,capture_receipt,validate_receipt
from indexer import TOKEN,digest,integer,publish
from master_history import identity,outbound
from provider import request,tonapi_request,paired
from recovery import read
from wallet_history import compare,successful,INTERNAL

def base_state(record,master):
    checked(record)
    require(record['version']==1 and record['anchor']==ANCHOR and record['master_digest']==master['digest'],
            'master base identity mismatch')
    last=master['transactions'][-1]
    raw=record['raw'];rows=raw['center']['transactions']
    require(len(rows)==1,'nonunique master anchor transaction')
    c,a=rows[0],raw['alternate']
    expected={k:v for k,v in last.items() if k not in ('outbound','in_opcode')}
    require(identity(c,False)==identity(a,True)==expected,'master anchor transaction mismatch')
    messages={m['message']:m for m in last['outbound']}
    require(outbound(c,False)==outbound(a,True)==messages,'master anchor outbound mismatch')
    require((c.get('in_msg') or {}).get('opcode')==last['in_opcode'],'master anchor opcode mismatch')
    row=compare(c,a,TOKEN)
    return cursor({'complete':True,'rows':[row],'head':record['digest'],
                   'prior':(row['lt'],row['tx'],row['state_after'])})

def capture_base(master,center,alternate):
    last=master['transactions'][-1];lt=last['lt']
    c,a=paired(lambda:center('transactions',{'account':TOKEN,'sort':'asc','limit':1,'start_lt':lt,'end_lt':lt}),
               lambda:alternate('blockchain/transactions/'+last['tx'],{}))
    record=signed({'version':1,'anchor':ANCHOR,'master_digest':master['digest'],'raw':{'center':c,'alternate':a}})
    return record,base_state(record,master)

def load(folder,master):
    state=base_state(read(folder/'base.json'),master)
    for i,path in enumerate(sorted((folder/'pages').glob('page-*.json'))):
        require(path.name==f'page-{i:08d}.json','master continuation sequence gap')
        state=apply(state,read(path),TOKEN,master['digest'])
    return state

def messages_from(rows):
    messages={};unknown=Counter()
    for row in rows:
        for m in row['out']:
            if m['token_opcode']!=INTERNAL:continue
            if not successful(row) or m['bounced'] is not False:
                unknown['failed_or_bounced']+=1;continue
            if m['source']!=TOKEN or not m['destination'] or m['amount_raw'] is None or integer(m['amount_raw'])<=0:
                unknown['unsupported_outbound']+=1;continue
            mid=m['hash'];require(mid not in messages,'duplicate master outbound message')
            messages[mid]={'message':mid,'wallet':m['destination'],'amount_raw':m['amount_raw'],
                           'master_tx':row['tx'],'master_lt':row['lt'],'master_at':row['time'],'master_aborted':False}
    return messages,dict(unknown)

def receipt_proof(record,msg,md,target):
    proof=validate_receipt(record,msg,md)
    raw=record['raw'];row=compare(raw['center']['transactions'][0],raw['alternate'],msg['wallet'])
    m=row['in']
    require(successful(row) and m and m['hash']==msg['message'] and m['source']==TOKEN
            and m['destination']==msg['wallet'] and m['bounced'] is False and m['token_opcode']==INTERNAL
            and m['amount_raw']==msg['amount_raw'] and row['lt']>msg['master_lt'],
            'master recipient normalized message mismatch')
    return proof,row

def run(store,center=request,alternate=tonapi_request,seconds=55):
    require(1<=seconds<=180,'invalid master continuation budget')
    master=read(store/'genesis'/'v1'/'master.json');historic_messages=validate_master(master);md=master['digest']
    target=integer(read(store/'update-status.json')['cutoff']);require(target>ANCHOR,'master target before anchor')
    folder=store/'continuation'/'v1'/'master';folder.mkdir(parents=True,exist_ok=True)
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    if not (folder/'base.json').exists():
        record,state=capture_base(master,center,alternate)
        publish(record,folder/'base.json')
    state=load(folder,master);require(state['target']<=target,'master continuation target rollback')
    previous_pages=state['pages'];previous_rows=len(state['new_rows'])
    stop=None;failure=None
    want=next_target(state,target)
    if want is not None:
        try:
            record,rows,complete=capture(TOKEN,state['prefix'],md,want,center,alternate)
            record=signed({**{k:v for k,v in record.items() if k!='digest'},'observed_at':int(time.time())})
            advanced=apply(state,record,TOKEN,md)
            require(len(advanced['new_rows'])-previous_rows==len(rows) and advanced['tip_reached']==complete,'master capture replay mismatch')
            dest=folder/'pages'/f"page-{state['pages']:08d}.json"
            require(not dest.exists(),'master continuation page already exists')
            dest.parent.mkdir(parents=True,exist_ok=True);publish(record,dest);state=advanced
        except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            stop=type(e).__name__;failure=str(e)[:240]
    require(load(folder,master)==state,'master cold replay mismatch')
    messages,unsupported=messages_from(state['new_rows'])
    require(not set(messages)&set(historic_messages),'post-anchor master message duplicates historical emission')
    dest=folder/'receipts';dest.mkdir(exist_ok=True)
    verified={}
    for path in sorted(dest.glob('*.json')):
        require(path.stem in messages,'orphan master continuation receipt')
        verified[path.stem]=receipt_proof(read(path),messages[path.stem],md,target)
    previous_receipts=len(verified)
    failures_path=folder/'pending.json'
    old=checked(read(failures_path)) if failures_path.exists() else {'master_digest':md,'failures':{}}
    require(old['master_digest']==md and set(old['failures'])<=set(messages),'master receipt pending mismatch')
    failures={k:v for k,v in old['failures'].items() if k not in verified}
    pending=sorted(set(messages)-set(verified),key=lambda k:(failures.get(k,{}).get('at',0),messages[k]['master_lt'],k))
    attempted=0
    for mid in pending[:10]:
        if time.monotonic()>=deadline:break
        if int(time.time())-failures.get(mid,{}).get('at',0)<600:continue
        attempted+=1
        try:
            record=capture_receipt(center,alternate,messages[mid],md)
            proof=receipt_proof(record,messages[mid],md,target)
        except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            failures[mid]={'at':int(time.time()),'reason':type(e).__name__+': '+str(e)[:180]}
            if isinstance(e,OSError) and getattr(e,'code',None)!=404:break
            continue
        path=dest/(mid+'.json');require(not path.exists(),'master receipt already exists')
        publish(record,path);verified[mid]=proof;failures.pop(mid,None)
    publish(signed({'master_digest':md,'failures':failures}),failures_path)
    inbound=Counter()
    for row in state['new_rows']:
        if row['in'] and row['in']['token_opcode']:
            inbound[row['in']['token_opcode']+('' if successful(row) else ':failed_or_unknown')]+=1
    summary={'version':1,'anchor':ANCHOR,'master_digest':md,'target_timestamp':target,'cursor_target':state['target'],
             'target_reached':state['tip_reached'] and state['target']==target,
             'last_transaction':state['prefix']['prior'][1],'last_lt':str(state['prefix']['prior'][0]),
             'total_envelopes':state['pages'],'replayed_envelopes':previous_pages,'new_envelopes':state['pages']-previous_pages,
             'post_anchor_master_rows':len(state['new_rows']),'new_rows_this_run':len(state['new_rows'])-previous_rows,
             'observed_token_inbound_opcodes':dict(inbound),'successful_internal_outbound':len(messages),
             'unsupported_outbound':unsupported,'verified_recipient_deliveries':len(verified),
             'verified_recipients_within_target':len({row['in']['destination'] for _,row in verified.values() if row['time']<=target}),
             'new_receipts':len(verified)-previous_receipts,'receipt_attempts':attempted,
             'pending_receipts':len(messages)-len(verified),'receipt_failure_reasons':dict(Counter(v['reason'] for v in failures.values())),
             'cold_replay_equal':True,'stop_reason':stop,'capture_failure':failure,
             'scope':'independent master account continuation and exact recipient observations; no supply calculation, full block completeness or economic classification'}
    publish(signed(summary),folder/'status.json')
    print('MASTER CONTINUATION',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--seconds',type=int,default=55);a=p.parse_args();run(a.store,seconds=a.seconds)
