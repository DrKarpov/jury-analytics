"""Compare verified wallet-chain observations with the existing transfer index.
Diagnostics only: never infer economic trades or modify the original candidate.
"""
import argparse
from collections import defaultdict,Counter
from pathlib import Path
from genesis_checkpoint import ANCHOR,signed,validate_master,validate_receipt
from wallet_history import INTERNAL,load_wallets,graph,inbound_frontier,successful
from incremental import load_history
from indexer import integer,publish
from recovery import read

def counterpart_index(states):
    # Include unlinked and unsuccessful observations, without expanding the
    # proven graph. An unresolved counterpart is evidence, not a delivery.
    incoming=defaultdict(list);outgoing=defaultdict(list)
    for w,s in states.items():
        for r in s['rows']:
            m=r['in']
            if m:incoming[m['hash']].append((w,r,m))
            for m in r['out']:outgoing[m['hash']].append((w,r,m))
    return incoming,outgoing

def gap_reason(side,expected,reference_lt,states,observations):
    wallet=expected['destination' if side=='recipient' else 'source']
    state=states.get(wallet)
    hits=observations.get(expected['hash'],[])
    if hits:
        if len(hits)!=1:return side+'_ambiguous_message_hash'
        w,r,m=hits[0]
        if w!=wallet or m!=expected:return side+'_message_fields_differ'
        if not successful(r):return side+'_failed_or_unknown_transaction'
        if (side=='recipient' and r['lt']<=reference_lt) or (side=='sender' and r['lt']>=reference_lt):
            return side+'_logical_time_conflict'
        return side+'_exact_counterpart_not_linked'
    if state is None:return side+'_not_scanned'
    if state.get('complete'):return side+'_missing_on_complete_chain'
    # A send preceding an observed receipt should already be present
    # if the ascending scan has passed the receipt's LT.
    if side=='sender' and state.get('prior') and state['prior'][0]>=reference_lt:
        return side+'_missing_in_scanned_prefix'
    return side+'_chain_incomplete'

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
    all_incoming,all_outgoing=counterpart_index(states)
    receipt_gaps=[];receipt_counts=Counter()
    for proof in receipts:
        w=proof['wallet'];s=states.get(w,{})
        found=observed.get(proof['recipient_tx'])
        if not found:
            if s.get('complete') or (s.get('prior') and s['prior'][0]>=integer(proof['recipient_lt'])):
                receipt_counts['missing_from_scanned_chain']+=1
                receipt_gaps.append({'message':proof['message'],'wallet':w,'tx':proof['recipient_tx'],'reason':'receipt_missing_from_scanned_chain'})
            else:receipt_counts['chain_not_yet_scanned_to_receipt']+=1
            continue
        account,r=found;m=r['in']
        if account!=w or not m or m['hash']!=proof['message'] or m['amount_raw']!=proof['amount_raw'] or not successful(r) or r['lt']!=integer(proof['recipient_lt']):
            receipt_counts['chain_conflict']+=1
            receipt_gaps.append({'message':proof['message'],'wallet':w,'tx':proof['recipient_tx'],'reason':'receipt_chain_conflict'})
        else:receipt_counts['observed_on_chain']+=1
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
        _,r,_=outgoing[mid]
        reason=gap_reason('recipient',m,r['lt'],states,all_incoming)
        gaps.append({'message':mid,'source_wallet':m['source'],'destination_wallet':m['destination'],
                     'amount_raw':m['amount_raw'],'reason':reason})
    upstream=[]
    for mid,m in sorted(inbound_frontier(states,linked,matched).items()):
        _,r,_=incoming[mid]
        reason=gap_reason('sender',m,r['lt'],states,all_outgoing)
        upstream.append({'message':mid,'source_wallet':m['source'],'destination_wallet':m['destination'],'amount_raw':m['amount_raw'],'reason':reason})
    if sum(receipt_counts.values())!=len(receipts):raise ValueError('receipt census mismatch')
    primary_on_chain=set(indexed)&set(observed)
    if not covered<=primary_on_chain:raise ValueError('index coverage inconsistent')
    return {'primary_records_at_anchor':len(indexed),'primary_hashes_on_linked_chains':len(primary_on_chain),
            'primary_coverage_counts':{'matched_endpoint_hash_amount':len(covered),
                'observed_hash_not_matched_endpoint':len(primary_on_chain-covered),
                'hash_not_observed_on_linked_chain':len(set(indexed)-primary_on_chain)},
            'master_receipt_chain_counts':dict(receipt_counts),
            'linked_accounts':len(linked),'linked_transactions':len(observed),'linked_messages':len(edges),
            'matched_deliveries':len(matched),'index_hash_amount_candidates':len(covered),
            'matched_status_counts':dict(Counter(x['status'] for x in results)),
            'unmatched_reason_counts':dict(Counter(x['reason'] for x in gaps)),
            'master_receipt_chain_gaps':receipt_gaps,'deliveries':results,'unmatched_messages':gaps,
            'unmatched_inbound_messages':upstream,'unmatched_inbound_reason_counts':dict(Counter(x['reason'] for x in upstream)),
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
    summary={k:v for k,v in r.items() if k not in ('deliveries','unmatched_messages','unmatched_inbound_messages','master_receipt_chain_gaps')}
    summary['master_receipt_chain_gap_count']=len(r['master_receipt_chain_gaps'])
    publish(signed({'version':1,'master_digest':master['digest'],'cutoff':ANCHOR,'history_head':h.head,'reconciliation_digest':out['digest'],**summary}),folder/'reconciliation-status.json')
    print(summary,flush=True)
    if r['master_receipt_chain_gaps']:raise ValueError('master receipt inconsistent with scanned wallet history')
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);a=p.parse_args();run(a.store)
