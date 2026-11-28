"""Acquire full predecessor prefixes for peers discovered by exact messages.

A prefix is pinned to an already replayed counterpart transaction, not a
moving latest tip. Initial identity and graph linkage have separate gates.
"""
import argparse,json,time
from collections import Counter,defaultdict
from functools import partial
from pathlib import Path
from canonical_movements import Observations
from continuation_shadow import require
from continuation_store import load as load_continuations
from counterpart_discovery import validate,record_key
from genesis_checkpoint import ANCHOR,checked,signed,validate_master,validate_receipt
from indexer import digest,integer,publish
from provider import request,tonapi_request,paired
from recovery import read
from wallet_history import compare,check_rows,graph,key,load_wallets,successful
from wallet_stateinit import inspect_record

def start(proof):
    row=proof['counterpart']
    return {'proof_digest':proof['digest'],'tip':{k:row[k] for k in ('tx','lt','time')},
            'prior':(0,None,None),'head':proof['digest'],'pages':0,'rows':[],
            'activation_observations':[],'complete':False}

def apply(state,record,proof,md):
    checked(record)
    wallet=proof['edge']['peer']
    require(record['version']==1 and record['master_digest']==md and record['wallet']==wallet
            and record['proof_digest']==state['proof_digest']==proof['digest']
            and record['previous_digest']==state['head'] and tuple(record['prior'])==state['prior']
            and record['sequence']==state['pages'] and not state['complete'],'peer prefix checkpoint identity mismatch')
    raw=record['raw'];c=raw['center']['transactions'];a=raw['alternate']['transactions']
    require(0<len(c)==len(a)<=record['size'],'peer prefix page missing or unequal')
    rows=[compare(x,y,wallet) for x,y in zip(c,a,strict=True)]
    prior=check_rows(rows,state['prior'],state['tip'],cutoff=proof['target'])
    complete=prior[0]==state['tip']['lt']
    if complete:require(rows[-1]==proof['counterpart'],'peer prefix tip differs from counterpart')
    activations=list(state['activation_observations'])
    for x,y,row in zip(c,a,rows,strict=True):
        if successful(row) and row['before']!='active' and row['after']=='active':
            obs={'tx':row['tx'],'before':row['before'],'proof':None,'reason':None}
            try:
                require(row['before'] in ('nonexist','uninit') and row['in'] and row['in']['bounced'] is False,
                        'unsupported activation')
                obs['proof']=inspect_record({'raw':{'center':{'transactions':[x]},'alternate':y}},
                       {'wallet':wallet,'message':row['in']['hash'],'recipient_tx':row['tx']})
            except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:obs['reason']=str(e)
            activations.append(obs)
    return {**state,'head':record['digest'],'prior':prior,'pages':state['pages']+1,
            'rows':state['rows']+rows,'complete':complete,'activation_observations':activations}

def capture(state,proof,md,center,alternate,size=100):
    w=proof['edge']['peer'];lt=state['tip']['lt'];prev=state['prior'][0]
    params={'sort_order':'asc','limit':size,'before_lt':lt+1}
    if prev:params['after_lt']=prev
    c,a=paired(lambda:center('transactions',{'account':w,'sort':'asc','limit':size,'start_lt':prev+1,'end_lt':lt}),
               lambda:alternate(f'blockchain/accounts/{w}/transactions',params))
    record=signed({'version':1,'master_digest':md,'wallet':w,'proof_digest':proof['digest'],
                   'previous_digest':state['head'],'prior':list(state['prior']),'sequence':state['pages'],
                   'size':size,'raw':{'center':c,'alternate':a}})
    return record,apply(state,record,proof,md)

def identity(state):
    a=state['activation_observations']
    if not state['complete']:return None,'prefix_incomplete'
    if len(a)!=1:return None,'activation_count_'+str(len(a))
    if a[0]['proof'] is None:return None,a[0]['reason']
    return a[0]['proof'],None

def load_prefixes(folder,proofs,md):
    result={}
    if not folder.exists():return result
    for d in sorted(folder.iterdir()):
        require(d.is_dir(),'unexpected peer prefix path')
        paths=sorted(d.glob('page-*.json'));require(bool(paths),'empty peer prefix')
        first=read(paths[0]);proof=proofs[first['proof_digest']]
        wallet=proof['edge']['peer'];require(d.name==key(wallet),'peer prefix filename mismatch')
        state=start(proof)
        for i,path in enumerate(paths):
            require(path.name==f'page-{i:08d}.json','peer prefix sequence gap')
            state=apply(state,read(path),proof,md)
        result[wallet]=state
    return result

def run(store,center=request,alternate=tonapi_request,limit=8,seconds=55):
    require(1<=limit<=30 and 1<=seconds<=180,'invalid peer budget')
    g=store/'genesis'/'v1';master=read(g/'master.json');md=master['digest'];messages=validate_master(master)
    roots=set()
    for p in sorted((g/'receipts').glob('*.json')):
        q=validate_receipt(read(p),messages[p.stem],md)
        if integer(q['recipient_at'])<=ANCHOR:roots.add(q['wallet'])
    states=load_wallets(g/'wallet-history',md)
    linked,_,_,_=graph(states,roots)
    eligible={w for w in linked if states.get(w,{}).get('complete') and states[w]['rows']}
    folder=store/'continuation'/'v1'
    cursors=load_continuations(folder/'accounts',states,eligible,md)
    known={r['tx']:(w,r) for w,s in states.items() for r in s['rows']}
    known.update({r['tx']:(w,r) for w,c in cursors.items() for r in c['new_rows']})
    proofs={};candidates=defaultdict(list)
    for path in sorted((folder/'counterparts').glob('*.json')):
        rec=read(path);e=rec['edge']
        require(path.stem==record_key(e),'counterpart filename mismatch')
        validate(rec,known.get(e['transaction']),md)
        proofs[rec['digest']]=rec
        # A peer can subsequently enter the historical graph; do not orphan
        # older evidence. Acquire from genesis when no complete prefix exists.
        if e['peer_state']=='not_in_historical_graph' or e['peer'] not in eligible:
            candidates[e['peer']].append(rec)
    dest=folder/'peer-prefixes'
    prefixes=load_prefixes(dest,proofs,md)
    previous_pages=sum(s['pages'] for s in prefixes.values())
    pending=folder/'peer-pending.json'
    old=checked(read(pending)) if pending.exists() else {'master_digest':md,'failures':{}}
    require(old['master_digest']==md,'peer pending identity mismatch')
    failures={w:v for w,v in old['failures'].items() if w in candidates or w in prefixes}
    now=int(time.time());deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    todo=set(candidates)|set(prefixes)
    todo=[w for w in todo if not prefixes.get(w,{}).get('complete') and now-failures.get(w,{}).get('at',0)>=600]
    todo.sort(key=lambda w:(w not in prefixes,
               not any(x['edge']['peer_state']=='not_in_historical_graph' for x in candidates.get(w,[])),
               failures.get(w,{}).get('at',0),w))
    attempted=written=0;stop=None
    for w in todo[:limit]:
        if time.monotonic()>=deadline:stop='budget';break
        attempted+=1
        if w in prefixes:
            s=prefixes[w];proof=proofs[s['proof_digest']]
        else:
            proof=max(candidates[w],key=lambda x:(x['counterpart']['lt'],x['digest']));s=start(proof)
        try:record,advanced=capture(s,proof,md,center,alternate)
        except OSError as e:
            failures[w]={'at':int(time.time()),'reason':type(e).__name__+': '+str(e)[:180]}
            if getattr(e,'code',None)==404:continue
            stop=type(e).__name__;break
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            failures[w]={'at':int(time.time()),'reason':str(e)[:200]};continue
        path=dest/key(w)/f"page-{s['pages']:08d}.json"
        require(not path.exists(),'peer prefix page already exists')
        path.parent.mkdir(parents=True,exist_ok=True);publish(record,path)
        prefixes[w]=advanced;written+=1;failures.pop(w,None)
    restored=load_prefixes(dest,proofs,md)
    require(restored==prefixes,'peer prefix cold replay mismatch')
    identities={};reasons=Counter()
    for w,s in restored.items():
        proof,why=identity(s)
        if proof:identities[w]=proof
        else:reasons[why]+=1
    # Only complete prefixes with initial StateInit proof enter this isolated
    # shadow projection. Any duplicate disagreement remains explicit, never
    # overwrite an existing normalized transaction or weaken its comparison.
    obs=Observations();obs.ingest(known.values());before=obs.project(roots)
    included=[];conflicts={}
    for w in sorted(identities):
        rows=restored[w]['rows']
        if any(x['tx'] in obs.rows and obs.rows[x['tx']]!=(w,x) for x in rows):
            conflicts[w]='normalized observation conflict';continue
        obs.ingest((w,x) for x in rows);included.append(w)
    after=obs.project(roots)
    previous={x['id']:x for x in before['events']};current={x['id']:x for x in after['events']}
    require(all(current.get(k)==v for k,v in previous.items()),'peer projection changed existing movement')
    summary={'version':1,'anchor':ANCHOR,'master_digest':md,'counterpart_records':len(proofs),
             'candidate_peers':len(candidates),'prefixes_started':len(restored),
             'complete_prefixes':sum(s['complete'] for s in restored.values()),
             'prefix_rows':sum(len(s['rows']) for s in restored.values()),
             'initial_stateinit_matches':len(identities),'identity_unresolved_reasons':dict(reasons),
             'included_shadow_prefixes':len(included),'projection_conflicts':conflicts,
             'additional_shadow_deliveries':len(current)-len(previous),'projection_digest':digest(after),
             'replayed_pages':previous_pages,'new_pages':written,'attempted_this_run':attempted,
             'pending_failure_peers':len(failures),'failure_reasons':dict(Counter(x['reason'] for x in failures.values())),
             'cold_replay_equal':True,'stop_reason':stop,
             'scope':'counterpart-pinned full prefixes and initial StateInit candidates; no current owner persistence, global completeness, balances or public trade labels'}
    folder.mkdir(parents=True,exist_ok=True)
    publish(signed({'master_digest':md,'failures':failures}),pending)
    publish(signed({**summary,'identities':identities,'included_wallets':included}),folder/'peer-status.json')
    print('PEER PREFIX DISCOVERY',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--limit',type=int,default=8);p.add_argument('--seconds',type=int,default=55);a=p.parse_args();run(a.store,limit=a.limit,seconds=a.seconds)
