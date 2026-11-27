"""Replay observed circular swaps without inventing a missing DEX quote.
A raw evidence record is replayed against the immutable indexed transfers.
Unknown first-leg quote is explicit and excluded from native quote metrics.
"""
from collections import Counter
from indexer import ROOT, TOKEN, digest, integer, hash_id
from provider import address
from recovery import read

FOLDER=ROOT/'config'/'arbitrage-evidence'
def evidence_records():
    return [read(p) for p in sorted(FOLDER.glob('*.json'))]

def candidate_pairs(rows,events):
    if len(rows)!=2 or any(r['aborted'] for r in rows):return []
    a,b=sorted(rows,key=lambda r:integer(r['lt']))
    if a['trace']!=b['trace'] or a['amount_raw']!=b['amount_raw'] or integer(a['amount_raw'])<=0 or a['destination']!=b['source'] or len({a['source'],a['destination'],b['destination']})!=3:return []
    sells=[e for e in events if e['kind']=='sell' and e['transfer_tx']==b['tx'] and e['quote_asset']=='GRAM' and e['wallet']==b['source']]
    if len(sells)!=1:return []
    if any(e['transfer_tx']==a['tx'] for e in events):return []
    return [(a,b,sells[0])]

def verify(record,rows,events):
    pairs=candidate_pairs(rows,events)
    if len(pairs)!=1:raise ValueError('cycle baseline mismatch')
    a,b,sell=pairs[0];t=record['trace'];stamp=record['time'];w,p,q=map(address,(record['owner'],record['first'],record['second']))
    if record['version']!=1 or t!=a['trace'] or (a['source'],a['destination'],b['destination'])!=(p,w,q) or any(x['time']!=stamp for x in (a,b,sell)):raise ValueError('cycle identity mismatch')
    obs=record['root_message']
    if obs['event_id']!=t or obs['in_progress'] is not False or obs['time']!=stamp:raise ValueError('event mismatch')
    transfers=[x for x in obs['actions'] if x['type']=='jetton_transfer' and x['status']=='ok' and address(x['jetton']['master'])==TOKEN and address(x['sender'])==p and address(x['recipient'])==w and x['amount']['raw']==a['amount_raw']]
    if len(transfers)!=1 or not any(x['action_name']=='JettonSwap' and x['status']=='ok' for x in obs['actions']):raise ValueError('event token flow absent')
    txs={hash_id(x['hash']):x for x in record['transactions']}
    if len(txs)!=len(record['transactions']) or any(x['time']!=stamp or x['success'] is not True for x in txs.values()):raise ValueError('raw transaction mismatch')
    root=txs[t]
    if address(root['account'])!=w or integer(root['lt'])>=integer(a['lt']) or integer(txs[a['tx']]['lt'])!=integer(a['lt']) or integer(txs[b['tx']]['lt'])!=integer(b['lt']):raise ValueError('raw transaction binding')
    def messages(x,direction,op=None,peer=None):
        return [m for m in x['messages'] if m['direction']==direction and (op is None or m['opcode']==op) and (peer is None or address(m['counterparty'])==peer)]
    def value(m):return integer(m['amount_gram']['raw'])
    def unique(xs):
        if len(xs)!=1:raise ValueError('ambiguous route')
        return xs[0]
    sent=unique(messages(root,'out','0xfa45056b',p))
    if value(sent)<=0:raise ValueError('zero call')
    # Reconcile all internal message endpoints by value/opcode and strictly increasing LT.
    # Only the root external input may be outside this recorded connected trace.
    outgoing=[];incoming=[]
    for x in txs.values():
        account=address(x['account'])
        for m in x['messages']:
            if m['bounced'] is not False or not m['counterparty']:raise ValueError('bounce or unknown endpoint')
            other=address(m['counterparty'])
            if m['direction']=='out':outgoing.append((account,other,m['opcode'],value(m),integer(x['lt'])))
            elif m['direction']=='in':incoming.append((other,account,m['opcode'],value(m),integer(x['lt'])))
            else:raise ValueError('invalid direction')
    for o in outgoing:
        matches=[i for i in incoming if i[:4]==o[:4] and i[4]>o[4]]
        if len(matches)!=1:raise ValueError('unmatched or ambiguous message')
    for i in incoming:
        matches=[o for o in outgoing if o[:4]==i[:4] and o[4]<i[4]]
        if len(matches)!=1:raise ValueError('unmatched incoming message')
    own=[x for x in txs.values() if address(x['account'])==w]
    received=sum(value(m) for x in own for m in messages(x,'in'))
    sent_total=sum(value(m) for x in own for m in messages(x,'out'))
    fees=sum(integer(x['fee_gram']['raw']) for x in own)
    payout=[m for x in own for m in messages(x,'in','0x3216ca09',q)]
    if value(unique(payout))!=integer(sell['quote_raw']):raise ValueError('sale settlement mismatch')
    # A jetton wallet transfer and internal transfer must form both sides of the same route.
    sa,sb=txs[a['tx']],txs[b['tx']]
    if not messages(sa,'in','0x0f8a7ea5',p) or not messages(sb,'in','0x0f8a7ea5',w):raise ValueError('transfer instruction mismatch')
    first_out=unique(messages(sa,'out','0x178d4519'))
    if address(first_out['counterparty'])!=address(sb['account']):raise ValueError('different intermediate jetton wallet')
    second_out=unique(messages(sb,'out','0x178d4519'))
    if address(second_out['counterparty'])==address(sa['account']):raise ValueError('unexpected return to first pool')
    proof=digest(record)
    buy={'id':digest({'trace':t,'transfer_tx':a['tx'],'rule':'observed_cycle_buy_v1'}),'trace':t,'time':stamp,'kind':'buy','wallet':w,'initiator':w,'amount_raw':a['amount_raw'],'quote_asset':'UNKNOWN','quote_raw':'0','quote_status':'unresolved','venue':'unknown','transfer_tx':a['tx']}
    return buy,{'trace':t,'wallet':w,'time':stamp,'amount_raw':a['amount_raw'],'buy_transfer':a['tx'],'sell_transfer':b['tx'],'native_received_raw':str(received),'native_sent_raw':str(sent_total),'wallet_fees_raw':str(fees),'native_net_raw':str(received-sent_total-fees),'buy_quote_status':'unresolved','proof_digest':proof,'scope':'connected wallet message cashflow; not gas-exclusive first DEX quote'}

def overlay(h):
    verified=[]
    for r in evidence_records():
        t=r['trace']
        if t not in h.traces:continue
        buy,cycle=verify(r,h.traces[t],h.events.get(t,[]))
        h.events[t]=sorted(h.events[t]+[buy],key=lambda e:e['id'])
        # All token legs have now been classified, but the first quote is still unresolved.
        h.unresolved[t]={'trace':t,'time':cycle['time'],'kind':'unresolved','transfer_count':0,'reasons':['missing_exact_buy_quote']}
        verified.append(cycle)
    candidates=sum(bool(candidate_pairs(rows,h.events.get(t,[]))) for t,rows in h.traces.items())
    return {'verified_cycles':verified,'additional_candidate_cycles':candidates,'scope':'only evidence-backed cycles classified; remaining candidates are not proven trades'}
