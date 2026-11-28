"""Bounded block enumeration feasibility pilot, read only.

No global watermark is advanced. Generic wallet code/opcodes are hints, not
master identity. Two indexer enumerations are not cryptographic block proofs.
"""
import argparse,gzip,json,time
from collections import Counter,defaultdict
from functools import partial
from pathlib import Path
from continuation_shadow import require
from continuation_store import load
from genesis_checkpoint import ANCHOR,checked,signed,validate_master,validate_receipt
from indexer import TOKEN,digest,hash_id,integer,publish
from provider import address,request,tonapi_request,paired
from recovery import read
from wallet_history import graph,load_wallets,compare,TOKEN_OPS

CODE='4b8b6932a0f8207b9e6c63a23418141cdb08cd95caec88007b0559d57b168835'

def ident(tx,alt):
    w=tx['account']['address'] if alt else tx['account']
    lt=integer(tx['lt']);require(lt>0,'invalid block transaction LT')
    return hash_id(tx['hash']),address(w),lt,integer(tx['utime' if alt else 'now'])

def enumerate_pages(fetch,seqno,alt,pages,size=100,max_pages=20):
    seen={}
    for n in range(max_pages):
        raw=fetch(f'blockchain/masterchain/{seqno}/transactions' if alt else 'transactionsByMasterchainBlock',
                  {'limit':size,'offset':n*size} if alt else {'seqno':seqno,'limit':size,'offset':n*size,'sort':'asc'})
        pages.append(raw);rows=raw['transactions']
        require(len(rows)<=size,'provider exceeded requested page size')
        for tx in rows:
            i=ident(tx,alt)
            require(i[0] not in seen,'duplicate block transaction across pages')
            if not alt:require(integer(tx['mc_block_seqno'])==seqno,'primary transaction belongs to another masterchain interval')
            seen[i[0]]=tx
        if len(rows)<size:return seen,True
    return seen,False

def hints(tx,alt,known_wallets):
    _,w,_,_=ident(tx,alt)
    result=set()
    if w==TOKEN:result.add('master')
    if w in known_wallets:result.add('known_linked_account')
    for m in [tx.get('in_msg'),*tx.get('out_msgs',[])]:
        if not m:continue
        op=m.get('op_code' if alt else 'opcode')
        if str(op).lower() in TOKEN_OPS:result.add('generic_jetton_opcode')
        for side in ('source','destination'):
            v=m.get(side)
            if isinstance(v,dict):v=v.get('address')
            if v and address(v)==TOKEN:result.add('master_message')
    if not alt:
        for k in ('account_state_before','account_state_after'):
            h=(tx.get(k) or {}).get('code_hash')
            if h and hash_id(h)==CODE:result.add('observed_wallet_code')
    return result

def inspect_block(seqno,c,a,complete_c,complete_a,known,known_wallets):
    both=set(c)&set(a)
    identity_mismatch=[h for h in sorted(both) if ident(c[h],False)!=ident(a[h],True)]
    expected={h for h,(_,r) in known.items() if r['mc_seqno']==seqno}
    candidates=[];issues=Counter();counts=Counter()
    for h in sorted(set(c)|set(a)):
        reasons=set()
        if h in c:reasons|=hints(c[h],False,known_wallets)
        if h in a:reasons|=hints(a[h],True,known_wallets)
        if h in expected:reasons.add('saved_transaction')
        if not reasons:continue
        for reason in reasons:counts[reason]+=1
        source=c[h] if h in c else a[h]
        _,w,lt,stamp=ident(source,h not in c)
        item={'tx':h,'wallet':w,'lt':str(lt),'time':stamp,'hints':sorted(reasons),
              'already_observed':h in known,'both_providers':h in both}
        if h in both and ('known_linked_account' in reasons or 'master' in reasons or 'observed_wallet_code' in reasons or h in expected):
            try:
                row=compare(c[h],a[h],w)
                item['normalized_comparison']='agree'
                if h in known and known[h]!=(w,row):
                    item['normalized_comparison']='saved_row_differs'
                    issues['saved_row_differs']+=1
            except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
                item['normalized_comparison']='unresolved'
                item['reason']=str(e)[:200];issues['normalization_unresolved']+=1
        candidates.append(item)
    return {'seqno':seqno,'center_rows':len(c),'alternate_rows':len(a),
            'center_terminal_page':complete_c,'alternate_terminal_page':complete_a,
            'common_hashes':len(both),'center_only':sorted(set(c)-set(a)),'alternate_only':sorted(set(a)-set(c)),
            'identity_mismatch':identity_mismatch,'enumerations_agree':complete_c and complete_a and set(c)==set(a) and not identity_mismatch,
            'expected_saved_rows':len(expected),'saved_rows_missing_center':sorted(expected-set(c)),
            'saved_rows_missing_alternate':sorted(expected-set(a)),
            'candidate_hints':dict(counts),'candidate_rows':len(candidates),
            'candidate_rows_not_previously_observed':sum(not x['already_observed'] for x in candidates),
            'known_linked_account_rows_not_previously_observed':sum(not x['already_observed'] and 'known_linked_account' in x['hints'] for x in candidates),
            'normalization_issues':dict(issues),'candidates':candidates}

def run(store,out,center=request,alternate=tonapi_request,seconds=180):
    g=store/'genesis'/'v1';master=read(g/'master.json');md=master['digest'];messages=validate_master(master)
    roots=set()
    for path in sorted((g/'receipts').glob('*.json')):
        q=validate_receipt(read(path),messages[path.stem],md)
        if integer(q['recipient_at'])<=ANCHOR:roots.add(q['wallet'])
    states=load_wallets(g/'wallet-history',md)
    linked,_,_,_=graph(states,roots)
    eligible={w for w in linked if states.get(w,{}).get('complete') and states[w]['rows']}
    folder=store/'continuation'/'v1';cursors=load(folder/'accounts',states,eligible,md)
    known={r['tx']:(w,r) for w,s in states.items() for r in s['rows']}
    known.update({r['tx']:(w,r) for w,c in cursors.items() for r in c['new_rows']})
    post=[r for c in cursors.values() for r in c['new_rows'] if r['mc_seqno']>0]
    require(bool(post),'no observed post-anchor block for pilot')
    seq=max(r['mc_seqno'] for r in post);require(seq>1,'invalid block pilot start')
    deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    out.mkdir(parents=True,exist_ok=True)
    reports=[]
    for n in (seq-1,seq):
        start=time.monotonic();cp=[];ap=[]
        try:
            (c,cc),(a,ac)=paired(lambda:enumerate_pages(center,n,False,cp),lambda:enumerate_pages(alternate,n,True,ap))
            report=inspect_block(n,c,a,cc,ac,known,linked)
        except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as exc:
            report={'seqno':n,'enumerations_agree':False,'error_type':type(exc).__name__,'error':str(exc)[:240]}
        raw=json.dumps({'seqno':n,'center_pages':cp,'alternate_pages':ap},ensure_ascii=False,separators=(',',':')).encode()
        path=out/f'block-{n}.json.gz'
        path.write_bytes(gzip.compress(raw,mtime=0))
        report.update(center_requests=len(cp),alternate_requests=len(ap),raw_bytes=len(raw),compressed_bytes=path.stat().st_size,
                      elapsed_seconds=round(time.monotonic()-start,3))
        reports.append(report)
        print('BLOCK PILOT',json.dumps({k:v for k,v in report.items() if k not in ('candidates','center_only','alternate_only','identity_mismatch','saved_rows_missing_center','saved_rows_missing_alternate')},sort_keys=True),flush=True)
    result={'version':1,'anchor':ANCHOR,'master_digest':md,'selection':'two consecutive intervals ending at latest observed post-anchor account transaction mc_seqno',
            'requested_seqnos':[seq-1,seq],'blocks':reports,'agreed_enumerations':sum(x['enumerations_agree'] for x in reports),
            'scope':'sampled independent block enumeration; no cryptographic proof, global completeness, master identity of generic candidates or production cursor'}
    publish(signed(result),out/'status.json')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.store,a.out)
