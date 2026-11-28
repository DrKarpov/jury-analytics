"""Pinned account-chain discovery from genesis receipts. No balance or trade inference."""
import argparse,time
from collections import defaultdict
from functools import partial
from pathlib import Path
from genesis_checkpoint import ANCHOR,checked,signed,validate_master,validate_receipt
from indexer import TOKEN,hash_id,integer,publish
from provider import address,request,tonapi_request,paired
from recovery import read

INTERNAL='0x178d4519'
TOKEN_OPS={INTERNAL,'0x0f8a7ea5','0x595f07bc','0x7bdd97de'}

def addr(v):
    if isinstance(v,dict):v=v.get('address')
    return address(v) if v else None

def message(m,alt):
    if not m:return None
    op=m.get('op_code' if alt else 'opcode')
    if op is not None:op=str(op).lower()
    b=m.get('bounced')
    if b is not None and type(b) is not bool:raise ValueError('invalid bounce flag')
    out={'hash':hash_id(m['hash']),'source':addr(m.get('source')),'destination':addr(m.get('destination')),
         'bounced':b,'token_opcode':op if op in TOKEN_OPS else None,'amount_raw':None}
    if out['token_opcode']:
        body=m.get('decoded_body') if alt else (m.get('message_content') or {}).get('decoded')
        if isinstance(body,dict) and body.get('amount') is not None:
            amount=body['amount']
            if isinstance(amount,dict):amount=amount['value']
            out['amount_raw']=str(integer(amount))
    return out

def row(tx,wallet,alt):
    if addr(tx['account'])!=wallet:raise ValueError('wrong account')
    prev=integer(tx.get('prev_trans_lt',0))
    aborted=tx['aborted'] if alt else tx['description']['aborted']
    if type(aborted) is not bool:raise ValueError('missing abort flag')
    if not alt and (tx.get('emulated') is not False or tx.get('finality')!='finalized'):
        raise ValueError('transaction not finalized')
    out=[message(m,alt) for m in tx['out_msgs']]
    if len({m['hash'] for m in out})!=len(out):raise ValueError('duplicate outgoing messages')
    return {'tx':hash_id(tx['hash']),'lt':integer(tx['lt']),'time':integer(tx['utime' if alt else 'now']),
            'previous_lt':prev,'previous_tx':hash_id(tx['prev_trans_hash']) if prev else None,
            'before':tx['orig_status'],'after':tx['end_status'],'aborted':aborted,
            'state_before':hash_id(tx['state_update_old'] if alt else tx['account_state_before']['hash']),
            'state_after':hash_id(tx['state_update_new'] if alt else tx['account_state_after']['hash']),
            'in':message(tx.get('in_msg'),alt),'out':sorted(out,key=lambda m:m['hash'])}

def compare(c,a,wallet):
    p,q=row(c,wallet,False),row(a,wallet,True)
    if p!=q:raise ValueError('provider wallet transaction mismatch: '+p['tx'])
    # Provider agreement is not a raw block proof. Code hash is separately observed from primary.
    p['code_before']=hash_id(c['account_state_before']['code_hash']) if c['account_state_before'].get('code_hash') else None
    p['code_after']=hash_id(c['account_state_after']['code_hash']) if c['account_state_after'].get('code_hash') else None
    p['mc_seqno']=integer(c['mc_block_seqno'])
    p['alternate_success']=a.get('success')
    return p

def pin(center,alternate,wallet):
    c=center('transactions',{'account':wallet,'sort':'desc','limit':1,'end_utime':ANCHOR})['transactions']
    if len(c)!=1:raise ValueError('no unique wallet tip')
    lt=integer(c[0]['lt'])
    a=alternate(f'blockchain/accounts/{wallet}/transactions',{'sort_order':'desc','limit':1,'before_lt':lt+1})['transactions']
    if len(a)!=1:raise ValueError('alternate wallet tip unavailable')
    r=compare(c[0],a[0],wallet)
    if not 0<r['time']<=ANCHOR:raise ValueError('wallet tip after anchor')
    return {'tx':r['tx'],'lt':lt,'time':r['time']}

def check_rows(rows,prior,tip):
    if not rows:raise ValueError('empty wallet page')
    prev_lt,prev_tx,state=prior
    for r in rows:
        if (r['previous_lt'],r['previous_tx'])!=(prev_lt,prev_tx) or not prev_lt<r['lt']<=tip['lt'] or not 0<r['time']<=ANCHOR:
            raise ValueError('wallet predecessor gap')
        if state is not None and r['state_before']!=state:raise ValueError('wallet state hash gap')
        prev_lt,prev_tx,state=r['lt'],r['tx'],r['state_after']
    if prev_lt==tip['lt'] and prev_tx!=tip['tx']:raise ValueError('wallet tip mismatch')
    return prev_lt,prev_tx,state

def fetch_page(center,alternate,wallet,tip,prior,size):
    p={'sort_order':'asc','limit':size,'before_lt':tip['lt']+1}
    if prior[0]:p['after_lt']=prior[0]
    c,a=paired(lambda:center('transactions',{'account':wallet,'sort':'asc','limit':size,'start_lt':prior[0]+1,'end_lt':tip['lt']})['transactions'],
               lambda:alternate(f'blockchain/accounts/{wallet}/transactions',p)['transactions'])
    if not c or len(c)!=len(a) or len(c)>size:raise ValueError('wallet page missing or unequal')
    rows=[compare(x,y,wallet) for x,y in zip(c,a,strict=True)]
    check_rows(rows,prior,tip)
    return rows

def key(wallet):return wallet.replace(':','_')

def load_wallets(folder,master_digest):
    states={}
    for p in sorted((folder/'accounts').glob('*/tip.json')):
        r=checked(read(p));wallet=r['wallet'];tip=r['tip']
        if r['master_digest']!=master_digest or r['cutoff']!=ANCHOR or p.parent.name!=key(wallet) or address(wallet)!=wallet:raise ValueError('wallet tip identity mismatch')
        prev=(0,None,None);head=r['digest'];rows=[];count=0
        for page in sorted(p.parent.glob('page-*.json')):
            b=checked(read(page))
            if b['wallet']!=wallet or b['tip_digest']!=r['digest'] or b['previous_digest']!=head or b['start_lt']!=prev[0] or page.name!=f"page-{count:08d}.json":
                raise ValueError('wallet checkpoint discontinuity')
            prev=check_rows(b['rows'],prev,tip);head=b['digest'];rows.extend(b['rows']);count+=1
        states[wallet]={'tip':tip,'tip_digest':r['digest'],'head':head,'prior':prev,'rows':rows,'pages':count,'complete':prev[0]==tip['lt']}
    return states

def valid_internal(m,w,direction):
    if not m or m['token_opcode']!=INTERNAL or m['bounced'] is not False:
        return False
    if not m['source'] or not m['destination'] or m['source']==TOKEN or m['destination']==TOKEN:
        return False
    return (m[direction]==w and m['amount_raw'] is not None and integer(m['amount_raw'])>0)

def successful(r):
    return r['aborted'] is False and r['alternate_success'] is True

def graph(states,roots):
    # Build the two indexes once. A new account becomes linked only through
    # a successful exact send/receipt pair, in either direction.
    incoming={};outgoing={}
    for w,s in states.items():
        for r in s['rows']:
            if not successful(r):continue
            m=r['in']
            if valid_internal(m,w,'destination'):
                if m['hash'] in incoming:raise ValueError('duplicate internal message receipt')
                incoming[m['hash']]=(w,r,m)
            for m in r['out']:
                if valid_internal(m,w,'source'):
                    if m['hash'] in outgoing:raise ValueError('duplicate internal message send')
                    outgoing[m['hash']]=(w,r,m)
    linked=set(roots);todo=list(sorted(linked));candidates=set(roots);edges={};matched=set()
    def link(w):
        candidates.add(w)
        if w not in linked:linked.add(w);todo.append(w)
    def match(mid):
        sent=outgoing.get(mid);received=incoming.get(mid)
        if sent is None or received is None:return
        w,r,m=sent;v,tx,n=received
        if m!=n or tx['lt']<=r['lt']:return
        matched.add(mid);link(w);link(v)
    while todo:
        w=todo.pop()
        for r in states.get(w,{}).get('rows',[]):
            if not successful(r):continue
            for m in r['out']:
                if not valid_internal(m,w,'source'):continue
                edges[m['hash']]=m;candidates.add(m['destination']);match(m['hash'])
            m=r['in']
            if valid_internal(m,w,'destination'):
                candidates.add(m['source']);match(m['hash'])
    return linked,candidates,edges,matched

def inbound_frontier(states,linked,matched):
    # Unlike outgoing edge counts, these are already observed receipts whose
    # upstream sender has not yet been independently matched.
    pending={}
    for w in linked:
        for r in states.get(w,{}).get('rows',[]):
            m=r['in']
            if successful(r) and valid_internal(m,w,'destination') and m['hash'] not in matched:
                if m['hash'] in pending:raise ValueError('duplicate pending inbound message')
                pending[m['hash']]=m
    return pending

def run(store,center,alternate,pages=24,size=50,seconds=200):
    if not 1<=pages<=100 or not 1<=size<=100 or seconds<=0:raise ValueError('invalid traversal budget')
    g=store/'genesis'/'v1';master=read(g/'master.json');messages=validate_master(master)
    roots=set()
    for p in sorted((g/'receipts').glob('*.json')):
        r=validate_receipt(read(p),messages[p.stem],master['digest'])
        if integer(r['recipient_at'])<=ANCHOR:roots.add(r['wallet'])
    folder=g/'wallet-history';folder.mkdir(parents=True,exist_ok=True)
    states=load_wallets(folder,master['digest'])
    pending_path=folder/'pending.json'
    old=checked(read(pending_path)) if pending_path.exists() else {'master_digest':master['digest'],'failures':{}}
    if old['master_digest']!=master['digest']:raise ValueError('wallet pending identity mismatch')
    failures=old['failures'];deadline=time.monotonic()+seconds;done=0;stop=None;tried=set()
    while done<pages and time.monotonic()<deadline:
        linked,candidates,edges,matched=graph(states,roots)
        options=[w for w in candidates if not states.get(w,{}).get('complete') and w not in tried]
        if not options:break
        # Alternate frontier closure and root discovery, so the graph does not spend
        # every batch on newly minted wallets while actual delivery edges stay open.
        weights=defaultdict(int)
        for mid,m in edges.items():
            if mid not in matched:weights[m['destination']]+=1
        for m in inbound_frontier(states,linked,matched).values():weights[m['source']]+=1
        def priority(x):
            return (failures.get(x,{}).get('at',0),
                    0 if (weights[x]>0 if done%2==0 else x in roots) else 1,
                    -weights[x],states.get(x,{}).get('pages',0),x)
        w=min(options,key=priority)
        try:
            dest=folder/'accounts'/key(w);dest.mkdir(parents=True,exist_ok=True)
            if w not in states:
                tip=pin(center,alternate,w)
                r=signed({'version':1,'master_digest':master['digest'],'cutoff':ANCHOR,'wallet':w,'tip':tip})
                publish(r,dest/'tip.json')
                states[w]={'tip':tip,'tip_digest':r['digest'],'head':r['digest'],'prior':(0,None,None),'rows':[],'pages':0,'complete':False}
            s=states[w]
            rows=fetch_page(center,alternate,w,s['tip'],s['prior'],size)
            b=signed({'version':1,'wallet':w,'tip_digest':s['tip_digest'],'previous_digest':s['head'],'start_lt':s['prior'][0],'rows':rows})
            path=dest/f"page-{s['pages']:08d}.json"
            if path.exists():raise RuntimeError('wallet page already exists')
            prev=check_rows(rows,s['prior'],s['tip'])
            publish(b,path)
            s.update(head=b['digest'],prior=prev,pages=s['pages']+1,complete=prev[0]==s['tip']['lt'])
            s['rows'].extend(rows);done+=1;failures.pop(w,None)
        except OSError as e:
            stop=type(e).__name__;break
        except (ValueError,KeyError,TypeError,AttributeError) as e:
            failures[w]={'at':int(time.time()),'reason':type(e).__name__+': '+str(e)[:200]};tried.add(w)
    states=load_wallets(folder,master['digest'])
    linked,candidates,edges,matched=graph(states,roots)
    upstream=inbound_frontier(states,linked,matched)
    publish(signed({'master_digest':master['digest'],'failures':failures}),pending_path)
    status={'version':1,'master_digest':master['digest'],'cutoff':ANCHOR,'root_wallets':len(roots),
            'linked_accounts':len(linked),'candidate_accounts':len(candidates),'unlinked_candidates':len(candidates-linked),
            'accounts_started':len(states),'linked_chains_complete':sum(states.get(w,{}).get('complete',False) for w in linked),
            'transactions_scanned':sum(len(s['rows']) for s in states.values()),'linked_transactions':sum(len(states.get(w,{}).get('rows',[])) for w in linked),
            'internal_messages':len(edges),'matched_internal_messages':len(matched),'unmatched_internal_messages':len(edges)-len(matched),
            'unmatched_inbound_messages':len(upstream),'upstream_candidate_accounts':len({m['source'] for m in upstream.values()}),
            'account_gaps':len(failures),'pages_this_run':done,'stop_reason':stop,
            'scope':'two-provider account chain/message linkage at pinned timestamp; no wallet code, token state, balance, burn or completeness certification'}
    publish(signed(status),folder/'status.json');print(status,flush=True)
    return status

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--pages',type=int,default=24);p.add_argument('--size',type=int,default=50);p.add_argument('--seconds',type=int,default=200);a=p.parse_args()
    deadline=time.monotonic()+a.seconds
    run(a.store,partial(request,deadline=deadline),partial(tonapi_request,deadline=deadline),a.pages,a.size,a.seconds)
