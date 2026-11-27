"""Compare verified wallet-chain observations with the existing transfer index.
Diagnostics only: never infer economic trades or modify the original candidate.
"""
import argparse
from collections import defaultdict,Counter
from pathlib import Path
from genesis_checkpoint import ANCHOR,signed,validate_master,validate_receipt
from wallet_history import INTERNAL,load_wallets,graph
from incremental import load_history
from indexer import integer,publish
from recovery import read

def compare_history(states,roots,receipts,primary):
    linked,candidates,edges,matched=graph(states,roots)
    indexed={r['tx']:r for r in primary.values() if r['time']<=ANCHOR}
    observed={r['tx']:(w,r) for w in linked for r in states.get(w,{}).get('rows',[])}
    outgoing={}
    incoming={}
    for w,r in observed.values():
        m=r['in']
        if m and m['token_opcode']==INTERNAL and m['destination']==w:
            incoming[m['hash']]=(w,r,m)
        for m in r['out']:
            if m['hash'] in edges:
                outgoing[m['hash']]=(w,r,m)
    receipt_gaps=[]
    for proof in receipts:
        w=proof['wallet'];s=states.get(w,{})
        found=observed.get(proof['recipient_tx'])
        if not found:
            if s.get('complete') or (s.get('prior') and s['prior'][0]>=integer(proof['recipient_lt'])):
                receipt_gaps.append({'message':proof['message'],'wallet':w,'tx':proof['recipient_tx'],'reason':'receipt_missing_from_scanned_chain'})
            continue
        account,r=found;m=r['in']
        if account!=w or not m or m['hash']!=proof['message'] or m['amount_raw']!=proof['amount_raw'] or r['aborted'] or r['lt']!=integer(proof['recipient_lt']):
            receipt_gaps.append({'message':proof['message'],'wallet':w,'tx':proof['recipient_tx'],'reason':'receipt_chain_conflict'})
    results=[];covered=set();missing=[];disagreements=[]
    for mid in sorted(matched):
        w,r,m=outgoing[mid];v,t,n=incoming[mid]
        # Compare candidate transaction hashes only. Source/destination in the legacy
        # index are owners, not jetton accounts. No ownership claim is made here.
        send,receive=indexed.get(r['tx']),indexed.get(t['tx'])
        exact=[x for x in (send,receive) if x and not x['aborted'] and x['amount_raw']==m['amount_raw']]
        candidate_ids=sorted({x['tx'] for x in exact})
        if candidate_ids:
            covered.update(candidate_ids)
            status='hash_amount_agree' if len(candidate_ids)==1 else 'multiple_index_candidates'
        elif send or receive:
            status='indexed_amount_or_status_differs'
            disagreements.append(mid)
        else:
            status='not_found_by_either_endpoint_tx_hash'
            missing.append(mid)
        results.append({'message':mid,'source_wallet':w,'destination_wallet':v,'sender_tx':r['tx'],'recipient_tx':t['tx'],
                        'sender_lt':str(r['lt']),'recipient_lt':str(t['lt']),'time':t['time'],'amount_raw':m['amount_raw'],
                        'index_candidates':candidate_ids,'status':status})
    gaps=[]
    for mid,m in sorted(edges.items()):
        if mid in matched:continue
        target=states.get(m['destination'],{})
        found=incoming.get(mid)
        reason='recipient_chain_incomplete'
        if found:reason='recipient_not_verified_or_mismatched'
        elif target.get('complete'):reason='recipient_missing_on_complete_chain'
        elif not target:reason='recipient_not_scanned'
        gaps.append({'message':mid,'source_wallet':m['source'],'destination_wallet':m['destination'],
                     'amount_raw':m['amount_raw'],'reason':reason})
    return {'primary_records_at_anchor':len(indexed),'primary_hashes_on_linked_chains':len(set(indexed)&set(observed)),
            'linked_accounts':len(linked),'linked_transactions':len(observed),'linked_messages':len(edges),
            'matched_deliveries':len(matched),'index_hash_amount_candidates':len(covered),
            'matched_status_counts':dict(Counter(x['status'] for x in results)),
            'unmatched_reason_counts':dict(Counter(x['reason'] for x in gaps)),
            'master_receipt_chain_gaps':receipt_gaps,'deliveries':results,'unmatched_messages':gaps,
            'scope':'Diagnostic two-provider matched message deliveries and endpoint hash/amount overlap; not economic trades, complete ledger, owner binding, or proof that missing hashes are omitted transfers.'}

def run(store):
    g=store/'genesis'/'v1';master=read(g/'master.json');messages=validate_master(master)
    receipts=[]
    for path in sorted((g/'receipts').glob('*.json')):
        proof=validate_receipt(read(path),messages[path.stem],master['digest'])
        if integer(proof['recipient_at'])<=ANCHOR:receipts.append(proof)
    folder=g/'wallet-history';states=load_wallets(folder,master['digest'])
    h=load_history(store)
    r=compare_history(states,{x['wallet'] for x in receipts},receipts,h.transfers)
    out=signed({'version':1,'master_digest':master['digest'],'cutoff':ANCHOR,'history_head':h.head,**r})
    publish(out,folder/'reconciliation.json')
    print({k:v for k,v in r.items() if k not in ('deliveries','unmatched_messages','master_receipt_chain_gaps')},flush=True)
    if r['master_receipt_chain_gaps']:raise ValueError('master receipt inconsistent with scanned wallet history')
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);a=p.parse_args();run(a.store)
