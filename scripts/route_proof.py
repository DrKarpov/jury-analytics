"""Causal message graph proof for a native -> JURY -> native cycle.

No hardcoded pool/owner addresses. The two indexed JURY rows must be
independently supported by decoded successful deliveries and notifications.
Native amounts are separate from gas; absent decoded principal stays unknown.
"""
from indexer import integer,hash_id,digest
from provider import address

NATIVE_SWAP={'0xfa45056b','0xea06185d','0x01f3835d'}
NATIVE_PAYOUT={'0x3216ca09','0x01f3835d','0x474f86cf','0x4cb700a9'}
def require(ok,reason):
    if not ok:raise ValueError(reason)
def one(items,reason):
    require(len(items)==1,reason+': '+str(len(items)))
    return items[0]
def val(m):return integer(m['amount_gram']['raw'])
def op(m):return str(m.get('opcode')).lower()
def addr(x):return address(x['address'] if isinstance(x,dict) else x)
def bodyint(b,k):
    v=b[k]
    return integer(v['value'] if isinstance(v,dict) else v)

def verify_route(record,a,b,sell):
    t=record['trace'];w,p,q=map(address,(record['owner'],record['first'],record['second']))
    stamp=record['time']
    require(t==a['trace']==b['trace'] and (a['source'],a['destination'],b['destination'])==(p,w,q),'cycle identity')
    txs={hash_id(x['hash']):x for x in record['transactions']}
    require(len(txs)==len(record['transactions']) and t in txs,'duplicate or missing transaction')
    require(all(x['success'] is True and integer(x['time'])>0 for x in txs.values()),'failed raw transaction')
    def account(h):return addr(txs[h]['account'])
    def lt(h):return integer(txs[h]['lt'])
    require(account(t)==w and lt(t)<integer(a['lt'])<integer(b['lt']),'root owner or LT mismatch')
    for r in (a,b):
        require(r['tx'] in txs and lt(r['tx'])==integer(r['lt']) and txs[r['tx']]['time']==r['time'],'indexed transaction binding')
    # Match by actual message hash (not value or timestamp). Every internal
    # message must have exactly one source and one destination in the tree.
    sends={};receives={}
    for h,x in txs.items():
        for m in x['messages']:
            require(m['bounced'] is False,'bounced message')
            mh=hash_id(m['message_hash'])
            require(m['direction'] in ('in','out'),'bad message direction')
            table=sends if m['direction']=='out' else receives
            require(mh not in table,'duplicate message endpoint')
            table[mh]=(h,m)
    require(sends.keys()==receives.keys(),'incomplete message graph')
    parents={};children={h:[] for h in txs}
    for mh,(u,m) in sends.items():
        v,n=receives[mh]
        require(addr(m['counterparty'])==account(v) and addr(n['counterparty'])==account(u) and val(m)==val(n) and op(m)==op(n) and lt(u)<lt(v),'inconsistent message endpoints')
        require(v not in parents,'multiple transaction parents')
        parents[v]=(u,n);children[u].append((v,m))
    require(set(parents)==set(txs)-{t},'disconnected graph')
    def path(start,end):
        rev=[];cur=end
        while cur!=start and cur in parents:
            prev,m=parents[cur];rev.append((prev,cur,m));cur=prev
        return list(reversed(rev)) if cur==start else []
    require(all(h==t or path(t,h) for h in txs),'disconnected trace')
    qty=integer(a['amount_raw'])
    def deliver(r):
        h=r['tx'];src,dst=r['source'],r['destination']
        parent,m=parents[h];d=m['body']
        require(account(parent)==src and op(m)=='0x0f8a7ea5','transfer instruction owner/opcode')
        require(addr(d['destination'])==dst and bodyint(d,'amount')==qty,'decoded transfer amount/destination')
        qid=bodyint(d,'query_id')
        target,im=one([(v,n) for v,n in children[h] if op(n)=='0x178d4519'],'internal transfer')
        d=im['body']
        require(bodyint(d,'amount')==qty and bodyint(d,'query_id')==qid and addr(d['from'])==src,'decoded internal transfer')
        notice,nm=one([(v,n) for v,n in children[target] if account(v)==dst and op(n)=='0x7362d09c'],'owner notification')
        d=nm['body']
        require(bodyint(d,'amount')==qty and bodyint(d,'query_id')==qid and addr(d['sender'])==src,'decoded token notification')
        return parent,target,notice
    pa,wa,na=deliver(a);pb,wb,nb=deliver(b)
    require(account(wa)==account(b['tx']) and pb==na,'token not spent by receiving notification')
    route=path(t,pa)
    require(bool(route),'no native input path')
    _,_,native=route[0]
    require(op(native) in NATIVE_SWAP and val(native)>0,'unrecognized native swap call')
    # A payout must descend from the actual second jetton delivery.
    # Use received message value for cashflow, not a fabricated DEX quote.
    settlements=[]
    for h in txs:
        if account(h)!=w or h not in parents:continue
        _,m=parents[h]
        if op(m) in NATIVE_PAYOUT and val(m)>0 and path(nb,h):settlements.append((h,m))
    payout_hash,payout=one(settlements,'native settlement path')
    require(val(payout)>0,'empty payout')
    own=[x for h,x in txs.items() if account(h)==w]
    received=sum(val(m) for x in own for m in x['messages'] if m['direction']=='in')
    sent=sum(val(m) for x in own for m in x['messages'] if m['direction']=='out')
    fees=sum(integer(x['fee_gram']['raw']) for x in own)
    # DeDust legacy native swap message defines amount:Coins explicitly.
    # Do not confuse total attached TON with swap principal.
    quote=None;venue='unknown'
    if op(native)=='0xea06185d':
        try:
            principal=bodyint(native['body'],'amount')
            if 0<principal<=val(native):quote=principal;venue='dedust'
        except (KeyError,ValueError,TypeError,AttributeError):pass
    buy={'id':digest({'trace':t,'transfer_tx':a['tx'],'rule':'observed_cycle_buy_v1'}),
         'trace':t,'time':stamp,'kind':'buy','wallet':w,'initiator':w,'amount_raw':a['amount_raw'],
         'quote_asset':'GRAM' if quote is not None else 'UNKNOWN','quote_raw':str(quote or 0),
         'quote_status':'verified' if quote is not None else 'unresolved','venue':venue,'transfer_tx':a['tx']}
    cycle={'trace':t,'wallet':w,'time':stamp,'amount_raw':a['amount_raw'],'buy_transfer':a['tx'],'sell_transfer':b['tx'],
           'native_received_raw':str(received),'native_sent_raw':str(sent),'wallet_fees_raw':str(fees),
           'native_net_raw':str(received-sent-fees),'native_payout_raw':str(val(payout)),
           'payout_tx':payout_hash,'buy_quote_status':buy['quote_status'],'proof_digest':digest(record),
           'scope':'causal decoded token deliveries and native cashflow; sale quote remains provider-reported'}
    return buy,cycle
