"""Shadow canonical internal-delivery projection shared by replay and future live ingestion.

Input is already independently compared wallet rows. This is NOT raw validation,
ownership, balance, mint/burn, or economic classification. Never publish as trades.
"""
import argparse,json
from collections import defaultdict
from pathlib import Path
from genesis_checkpoint import ANCHOR,validate_master,validate_receipt,checked,signed
from indexer import digest,hash_id,integer,publish
from provider import address
from recovery import read
from wallet_history import graph,load_wallets,successful,valid_internal

class Observations:
    def __init__(self):
        self.rows={}
    def ingest(self,items):
        for wallet,row in items:
            if address(wallet)!=wallet or hash_id(row['tx'])!=row['tx']:
                raise ValueError('invalid canonical observation identity')
            key=row['tx'];value=(wallet,row)
            if key in self.rows and self.rows[key]!=value:
                raise ValueError('conflicting transaction observation')
            self.rows[key]=value
    def project(self,roots):
        states=defaultdict(lambda:{'rows':[]})
        for wallet,row in self.rows.values():states[wallet]['rows'].append(row)
        linked,candidates,edges,matched=graph(states,roots)
        sends={};receipts={}
        for wallet in linked:
            for r in states.get(wallet,{}).get('rows',[]):
                if not successful(r):continue
                m=r['in']
                if valid_internal(m,wallet,'destination') and m['hash'] in matched:
                    receipts[m['hash']]=(wallet,r)
                for m in r['out']:
                    if m['hash'] in matched and valid_internal(m,wallet,'source'):
                        sends[m['hash']]=(wallet,r)
        events=[];net=defaultdict(int)
        for mid in sorted(matched):
            src,s=sends[mid];dst,t=receipts[mid];m=edges[mid]
            qty=integer(m['amount_raw'])
            events.append({'id':mid,'kind':'matched_internal_delivery','source_wallet':src,'destination_wallet':dst,
                           'sender_tx':s['tx'],'recipient_tx':t['tx'],'sender_lt':str(s['lt']),'recipient_lt':str(t['lt']),
                           'amount_raw':str(qty),'recipient_time':t['time']})
            net[src]-=qty;net[dst]+=qty
        if sum(net.values())!=0:raise ValueError('internal movement conservation failure')
        return {'version':1,'rule':'matched_internal_delivery_v1','linked_accounts':len(linked),'candidate_accounts':len(candidates),
                'observed_outgoing_messages':len(edges),'matched_deliveries':len(events),
                'events':events,'net_internal_movements_raw':{w:str(n) for w,n in sorted(net.items())},
                'scope':'exact paired internal deliveries only; net internal movement is not balance, supply or trade volume'}

def run(store,out):
    g=store/'genesis'/'v1';master=read(g/'master.json');messages=validate_master(master)
    roots=set()
    for p in sorted((g/'receipts').glob('*.json')):
        q=validate_receipt(read(p),messages[p.stem],master['digest'])
        if integer(q['recipient_at'])<=ANCHOR:roots.add(q['wallet'])
    folder=g/'wallet-history'
    states=load_wallets(folder,master['digest'])
    items=[(w,r) for w,s in states.items() for r in s['rows']]
    full=Observations();full.ingest(items);result=full.project(roots)
    batched=Observations()
    for start in range(len(items),0,-257):
        batch=items[max(0,start-257):start]
        batched.ingest(reversed(batch));batched.ingest(batch)
    other=batched.project(roots)
    if result!=other:raise ValueError('canonical projection differs by arrival order or duplicates')
    status=checked(read(folder/'status.json'))
    if status['master_digest']!=master['digest'] or status['cutoff']!=ANCHOR:
        raise ValueError('shadow status identity mismatch')
    expected=(status['transactions_scanned'],status['linked_accounts'],status['candidate_accounts'],status['internal_messages'],status['matched_internal_messages'])
    actual=(len(full.rows),result['linked_accounts'],result['candidate_accounts'],result['observed_outgoing_messages'],result['matched_deliveries'])
    if actual!=expected:raise ValueError('shadow projection differs from pinned checkpoint')
    summary={'anchor':ANCHOR,'master_digest':master['digest'],'wallet_status_digest':status['digest'],'input_rows':len(full.rows),
             'matched_deliveries':result['matched_deliveries'],'observed_outgoing_messages':result['observed_outgoing_messages'],
             'net_internal_sum_raw':'0','projection_digest':digest(result),'reordered_duplicate_batch_replay_equal':True,
             'scope':'shadow historical normalized-row replay, not actual live ingest parity or full ledger'}
    out.parent.mkdir(parents=True,exist_ok=True)
    publish(signed({**summary,'projection':result}),out)
    print('CANONICAL SHADOW',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.store,a.out)
