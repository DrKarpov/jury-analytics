"""Inventory all observed token movements, independent of economic action labels.

A topology is a review hint, never proof of swaps, LP, fees or common ownership.
The account-chain report works at the pinned historical anchor; the trace report
works at the latest indexed cutoff. These distinct scopes must not be merged.
"""
import argparse
from collections import Counter,defaultdict
from pathlib import Path
from indexer import TOKEN,integer,publish,digest
from genesis_checkpoint import ANCHOR,signed,validate_master,validate_receipt
from wallet_history import INTERNAL,load_wallets,graph
from recovery import read

BURN='0x595f07bc'
BURN_NOTIFY='0x7bdd97de'
TRANSFER='0x0f8a7ea5'

def successful(r):
    return r['aborted'] is False and r['alternate_success'] is True

def wallet_inventory(states,roots,receipts):
    linked,candidates,edges,matched=graph(states,roots)
    mint={r['message']:r for r in receipts}
    counts=Counter();issues=[];code_hashes=Counter()
    seen_in=set();seen_out=set()
    def issue(kind,w,r,m):
        issues.append({'kind':kind,'wallet':w,'tx':r['tx'],'lt':str(r['lt']),
                       'message':m['hash'],'source':m['source'],'destination':m['destination'],
                       'amount_raw':m['amount_raw'],'opcode':m['token_opcode']})
    for w in sorted(linked):
        for r in states.get(w,{}).get('rows',[]):
            counts['account_transactions']+=1
            counts['successful_transactions' if successful(r) else 'failed_or_unknown_transactions']+=1
            if r.get('code_after'):code_hashes[r['code_after']]+=1
            for direction,items in (('in',[r['in']] if r['in'] else []),('out',r['out'])):
                for m in items:
                    counts[direction+'_messages']+=1
                    op=m['token_opcode']
                    if op not in (INTERNAL,TRANSFER,BURN,BURN_NOTIFY):
                        # v1 normalization intentionally did not retain all opcodes.
                        counts[direction+'_other_or_unretained_opcode']+=1
                        if m['bounced'] is True:issue('bounced_other_message',w,r,m)
                        continue
                    counts[direction+'_'+op]+=1
                    if m['bounced'] is True:
                        issue('bounced_token_message',w,r,m);continue
                    if not successful(r):
                        issue('failed_or_unknown_token_transaction',w,r,m);continue
                    if m['amount_raw'] is None:
                        issue('missing_decoded_amount',w,r,m);continue
                    if integer(m['amount_raw'])<=0:
                        issue('nonpositive_token_amount',w,r,m);continue
                    if op==INTERNAL and direction=='in':
                        if m['hash'] in seen_in:raise ValueError('duplicate incoming token message')
                        seen_in.add(m['hash'])
                        if m['hash'] in mint:
                            proof=mint[m['hash']]
                            if m['source']!=TOKEN or proof['wallet']!=w or proof['recipient_tx']!=r['tx'] or proof['amount_raw']!=m['amount_raw']:
                                issue('mint_receipt_conflict',w,r,m)
                            else:counts['mint_receipts_on_scanned_chain']+=1
                        elif m['hash'] in matched:
                            counts['matched_internal_receipts']+=1
                        else:issue('unpaired_internal_receipt',w,r,m)
                    elif op==INTERNAL and direction=='out':
                        if m['hash'] in seen_out:raise ValueError('duplicate outgoing token message')
                        seen_out.add(m['hash'])
                        if m['hash'] in matched:counts['matched_internal_sends']+=1
                        elif m['hash'] in edges:issue('unpaired_internal_send',w,r,m)
                        else:issue('internal_send_outside_graph',w,r,m)
                    elif op in (BURN,BURN_NOTIFY):
                        issue('burn_instruction_or_notification',w,r,m)
                    elif op==TRANSFER:
                        counts['transfer_instructions']+=1
    if counts['matched_internal_receipts']!=len(matched) or counts['matched_internal_sends']!=len(matched):
        raise ValueError('matched internal message census inconsistent')
    return {'linked_accounts':len(linked),'candidate_accounts':len(candidates),
            'complete_linked_chains':sum(states.get(w,{}).get('complete',False) for w in linked),
            'master_receipts':len(mint),'matched_internal_deliveries':len(matched),
            'message_counts':dict(sorted(counts.items())),'observed_code_after_hashes_by_tx':dict(sorted(code_hashes.items())),
            'review_counts':dict(sorted(Counter(x['kind'] for x in issues).items())),
            'review_messages':issues,
            'scope':'Pinned two-provider account history, review flags only. v1 does not preserve all non-token opcodes or bounce payloads; no claim of complete burns, balance or protocol decoding.'}

def topology(rows):
    """A graph of token owner endpoints, not of complete TON messages."""
    ok=[r for r in rows if r['aborted'] is False and integer(r['amount_raw'])>0]
    inputs=defaultdict(list);outputs=defaultdict(list)
    for r in ok:
        inputs[r['destination']].append(r);outputs[r['source']].append(r)
    flags=[]
    if any(r['aborted'] for r in rows):flags.append('aborted_transfer')
    if any(integer(r['amount_raw'])==0 for r in rows):flags.append('zero_amount')
    if any(r['source']==r['destination'] for r in ok):flags.append('self_transfer')
    if any(len({r['destination'] for r in es})>1 for es in outputs.values()):flags.append('fan_out')
    if any(len({r['source'] for r in es})>1 for es in inputs.values()):flags.append('fan_in')
    if len(ok)>1 and any(w in inputs and w in outputs for w in set(inputs)|set(outputs)):flags.append('chained')
    # Directed cycle is only a topology flag. An arbitrage may have no JURY cycle.
    indegree=Counter(r['destination'] for r in ok)
    nodes=set(inputs)|set(outputs);queue=[w for w in nodes if indegree[w]==0];seen=0
    while queue:
        w=queue.pop();seen+=1
        for r in outputs[w]:
            d=r['destination'];indegree[d]-=1
            if indegree[d]==0:queue.append(d)
    if seen<len(nodes):flags.append('directed_cycle')
    if len(ok)==1:flags.append('single_positive_transfer')
    elif len(ok)>1:flags.append('multiple_positive_transfers')
    else:flags.append('no_positive_successful_transfer')
    return sorted(flags)

def trace_inventory(h):
    shape=Counter();pending_shape=Counter();counts=Counter();reasons=Counter();queue=[]
    for t,rows in sorted(h.traces.items()):
        es=h.events.get(t,[]);used={e['transfer_tx'] for e in es};ids={r['tx'] for r in rows}
        if len(ids)!=len(rows) or len(used)!=len(es) or not used<=ids:raise ValueError('invalid trace coverage')
        flags=topology(rows);shape.update(flags)
        counts['traces']+=1;counts['indexed_transfers']+=len(rows);counts['classified_transfer_rows']+=len(used)
        remaining=[r for r in rows if r['tx'] not in used]
        counts['unclassified_transfer_rows']+=len(remaining)
        u=h.unresolved.get(t)
        if u is not None and u['transfer_count']!=len(remaining):raise ValueError('unresolved transfer count mismatch')
        if remaining or u is not None:
            counts['traces_requiring_review']+=1;pending_shape.update(flags)
            why=sorted(set((u or {}).get('reasons',[])))
            reasons.update(why)
            queue.append({'trace':t,'time':max(r['time'] for r in rows),'transfer_rows':len(rows),
                          'unclassified_tx':[r['tx'] for r in remaining],
                          'topology':flags,'reasons':why,'classified_kinds':dict(Counter(e['kind'] for e in es))})
        else:counts['traces_without_unresolved_flag']+=1
    if counts['indexed_transfers']!=counts['classified_transfer_rows']+counts['unclassified_transfer_rows']:
        raise ValueError('transfer coverage arithmetic')
    return {'cutoff':h.cutoff,'history_head':h.head,'counts':dict(counts),
            'all_trace_topologies_nonexclusive':dict(sorted(shape.items())),
            'review_trace_topologies_nonexclusive':dict(sorted(pending_shape.items())),
            'unresolved_reasons_nonexclusive':dict(sorted(reasons.items())),
            'review_queue':queue,
            'scope':'All indexed transfer traces after existing verified overlays; topology flags are not economic labels. LP deposits, withdrawals, splits, fee/refunds, unknown protocols and multi-hop require raw evidence.'}

def run(store):
    from persistent_preview import corrected_history
    g=store/'genesis'/'v1';master=read(g/'master.json');messages=validate_master(master)
    receipts=[]
    for path in sorted((g/'receipts').glob('*.json')):
        r=validate_receipt(read(path),messages[path.stem],master['digest'])
        if integer(r['recipient_at'])<=ANCHOR:receipts.append(r)
    states=load_wallets(g/'wallet-history',master['digest'])
    wallets=wallet_inventory(states,{r['wallet'] for r in receipts},receipts)
    h,*_=corrected_history(store)
    traces=trace_inventory(h)
    folder=store/'inventory'/'v1';folder.mkdir(parents=True,exist_ok=True)
    publish(signed({'version':1,'cutoff':ANCHOR,'master_digest':master['digest'],**wallets}),folder/'wallets.json')
    publish(signed({'version':1,**traces}),folder/'traces.json')
    summary={'anchor':ANCHOR,'index_cutoff':h.cutoff,'history_head':h.head,
             'wallets':{k:v for k,v in wallets.items() if k!='review_messages'},
             'traces':{k:v for k,v in traces.items() if k!='review_queue'}}
    publish(signed(summary),folder/'status.json')
    print('HISTORY INVENTORY',summary,flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);a=p.parse_args();run(a.store)
