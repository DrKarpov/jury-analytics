"""Inspect historical deployment transactions of linked JURY accounts.
Read-only, bounded capture; raw observations must replay against saved account rows.
"""
import argparse,base64,json,time
from collections import Counter,defaultdict
from functools import partial
from pathlib import Path
from genesis_checkpoint import ANCHOR,validate_master,validate_receipt,signed
from indexer import integer,publish
from provider import request,tonapi_request,paired
from recovery import read
from wallet_history import load_wallets,graph,compare,successful
from wallet_stateinit import require,inspect_record

def activation(state):
    rows=state.get('rows',[])
    if not rows:return None,'chain_not_scanned'
    active=[r for r in rows if r['before']!='active' and r['after']=='active' and successful(r)]
    if not active:return None,'activation_not_observed'
    if len(active)!=1:return None,'multiple_activations'
    r=active[0]
    if r['before'] not in ('nonexist','uninit'):return None,'unsupported_activation_status'
    m=r['in']
    if not m or m['bounced'] is not False or m['destination'] is None:return None,'unsupported_activation_message'
    return r,None

def replay(wallet,row,raw):
    c=raw['center']['transactions'];a=raw['alternate']
    require(len(c)==1,'nonunique activation transaction')
    try:observed=compare(c[0],a,wallet)
    except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
        raise ValueError('activation row replay: '+str(e)) from e
    require(observed==row,'activation differs from saved chain')
    require(successful(row) and row['before'] in ('nonexist','uninit') and row['after']=='active','not successful initial activation')
    require(row['in'] and row['in']['destination']==wallet and row['in']['bounced'] is False,'wrong activation message')
    proof={'wallet':wallet,'message':row['in']['hash'],'recipient_tx':row['tx']}
    c_after=c[0].get('account_state_after') or {}
    require(c_after.get('code_hash') is not None,'activation historical code_after hash missing')
    try:return inspect_record({'raw':raw},proof)
    except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
        raise ValueError('activation StateInit: '+str(e)) from e

def capture(wallet,row,center,alternate,attempts):
    key=row['in']['hash'];enc=base64.b64encode(bytes.fromhex(key)).decode('ascii')
    c,a=paired(lambda:center('transactionsByMessage',{'msg_hash':enc,'direction':'in','limit':2}),
               lambda:alternate(f'blockchain/messages/{key}/transaction',{}))
    raw={'center':c,'alternate':a}
    attempts.append({'method':'message','raw':raw})
    try:return raw,replay(wallet,row,raw)
    except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
        attempts[-1]['error']=str(e)
        # Query the exact LT via the same account endpoints used in the
        # original chain traversal. Do not splice fields from different
        # responses or relax exact normalized row agreement.
        lt=row['lt']
        c,a=paired(lambda:center('transactions',{'account':wallet,'sort':'asc','limit':1,'start_lt':lt,'end_lt':lt}),
                   lambda:alternate(f'blockchain/accounts/{wallet}/transactions',{'sort_order':'asc','limit':1,'after_lt':lt-1,'before_lt':lt+1}))
        a_rows=a['transactions']
        require(len(a_rows)==1,'account fallback nonunique alternate transaction')
        raw={'center':c,'alternate':a_rows[0]}
        attempts.append({'method':'account_lt','raw':raw})
        try:return raw,replay(wallet,row,raw)
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            attempts[-1]['error']=str(e)
            raise

def code_observation(state,initial):
    # A state hash chain is not a complete proof of persistent data semantics.
    # Missing code or differing code is explicitly reported, never inferred.
    rows=state['rows'];expected=initial['code_hash']
    live=[r for r in rows if r['after']=='active']
    changes=sum(r.get('code_after') not in (None,expected) for r in live)
    missing=sum(r.get('code_after') is None for r in live)
    inactive=sum(r['after']!='active' for r in rows)
    return {'active_rows':len(live),'different_code_rows':changes,'missing_code_rows':missing,'inactive_rows':inactive,'chain_complete':state['complete']}

def run(store,out,center=request,alternate=tonapi_request,limit=30,seconds=115):
    require(1<=limit<=60 and 1<=seconds<=180,'invalid deployment audit budget')
    g=store/'genesis'/'v1';master=read(g/'master.json');messages=validate_master(master)
    roots=set();mint=defaultdict(list)
    for p in sorted((g/'receipts').glob('*.json')):
        record=read(p);proof=validate_receipt(record,messages[p.stem],master['digest'])
        if integer(proof['recipient_at'])>ANCHOR:continue
        roots.add(proof['wallet']);mint[proof['wallet']].append(inspect_record(record,proof))
    states=load_wallets(g/'wallet-history',master['digest'])
    linked,candidates,_,_=graph(states,roots)
    queue=[];unavailable=[];root_checks=[]
    for w in sorted(linked):
        state=states.get(w,{})
        if w in roots:
            ids={(x['owner_candidate'],x['master_candidate'],x['code_hash'],x['data_hash']) for x in mint[w]}
            require(len(ids)==1,'conflicting root StateInit identity')
            if state.get('rows'):
                root_checks.append({'wallet':w,**code_observation(state,mint[w][0])})
            continue
        row,why=activation(state)
        if why:unavailable.append({'wallet':w,'reason':why});continue
        queue.append((w,row))
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    records=[];failures=[];attempted=0;stop=None
    for w,row in queue[:limit]:
        if time.monotonic()>=deadline:stop='budget';break
        attempted+=1;attempts=[]
        try:raw,initial=capture(w,row,center,alternate,attempts)
        except OSError as e:
            stop=type(e).__name__;failures.append({'wallet':w,'tx':row['tx'],'reason':str(e),'attempts':attempts});break
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            failures.append({'wallet':w,'tx':row['tx'],'reason':str(e),'attempts':attempts});continue
        records.append({'wallet':w,'activation':row,'chain_tip_digest':states[w]['tip_digest'],
                        'initial':initial,'code_observation':code_observation(states[w],initial),'raw':raw,'capture_method':attempts[-1]['method'],'attempts':attempts})
    summary={'anchor':ANCHOR,'master_digest':master['digest'],'root_wallets':len(roots),'linked_accounts':len(linked),
             'candidate_accounts':len(candidates),'nonroot_linked_wallets':len(linked-roots),
             'root_wallets_with_scanned_code':len(root_checks),
             'root_wallets_with_different_code':sum(x['different_code_rows']>0 for x in root_checks),
             'root_wallets_with_missing_code':sum(x['missing_code_rows']>0 for x in root_checks),
             'activation_candidates':len(queue),'unavailable_activations':len(unavailable),
             'unavailable_reasons':dict(Counter(x['reason'] for x in unavailable)),
             'attempted':attempted,'matching_initial_state':len(records),'failed':len(failures),
             'unattempted_candidates':len(queue)-attempted,'failure_reasons':dict(Counter(x['reason'] for x in failures)),
             'verified_with_different_code':sum(x['code_observation']['different_code_rows']>0 for x in records),
             'verified_with_missing_code':sum(x['code_observation']['missing_code_rows']>0 for x in records),
             'capture_methods':dict(Counter(x['capture_method'] for x in records)),
             'first_attempt_errors':dict(Counter(x['attempts'][0]['error'] for x in records+failures if x['attempts'] and 'error' in x['attempts'][0])),
             'stop_reason':stop,'scope':'Bounded linked non-mint initial activation and historical code observations; not owner persistence, block proof, balance or trade classification'}
    publish(signed({**summary,'records':records,'failures':failures,'unavailable':unavailable,'root_code_checks':root_checks}),out)
    print('LINKED DEPLOYMENT DIAGNOSTIC',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--limit',type=int,default=30);a=p.parse_args();run(a.store,a.out,limit=a.limit)
