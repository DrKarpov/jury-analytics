"""Conservative DeDust CPMM v2 liquidity settlement evidence, not trade volume."""
import base64
from indexer import integer,hash_id
from provider import address
from discrepancy import tree_index
POOL_CODE='ba1622d85268da7fa39cfc09df5c069e904899cc6522bf97d1d3443fc89d0ec6'
JOIN,EXIT,CREDIT='0x25251ee0','0xf6f6a3aa','0x855afcbd'
WITHDRAW,POSITION_WITHDRAW,DEPOSIT_CREDIT='0x20b5ef89','0xbc1531a9','0xdc5ddba1'
TRANSFER,INTERNAL,NOTIFY='0x0f8a7ea5','0x178d4519','0x7362d09c'
def need(ok,why):
    if not ok:raise ValueError(why)
def one(xs,why):
    need(len(xs)==1,why+': '+str(len(xs)))
    return xs[0]
def account(x):return address(x['account']['address'])
def peer(m,k):return address(m[k]['address'])
def op(m):return str(m.get('op_code','')).lower()
def good(x):return x.get('success') is True and x.get('aborted') is False
def uid(x):return hash_id(x['hash'])
def lt(x):return integer(x['lt'])
def body(m):return m['decoded_body']

class Graph:
    def __init__(self,tree,t):
        self.txs=tree_index(tree,t);self.parents={};self.children={h:[] for h in self.txs}
        stack=[tree];seen=set()
        while stack:
            n=stack.pop();x=n['transaction'];h=uid(x);actual=set()
            for c in n.get('children') or []:
                y=c['transaction'];v=uid(y);m=y['in_msg'];mid=hash_id(m['hash'])
                need(v not in self.parents and mid not in seen,'duplicate causal message')
                need(m.get('msg_type')=='int_msg' and peer(m,'source')==account(x) and peer(m,'destination')==account(y) and lt(x)<lt(y),'invalid message edge')
                if m.get('created_lt') is not None:need(lt(x)<integer(m['created_lt'])<lt(y),'invalid message logical time')
                self.parents[v]=(h,m);self.children[h].append((v,m));seen.add(mid);actual.add(mid);stack.append(c)
            declared={hash_id(m['hash']) for m in x.get('out_msgs',[]) if m.get('msg_type')=='int_msg'}
            if declared:need(declared==actual,'incomplete trace outputs')
        need(set(self.parents)==set(self.txs)-{t},'incomplete trace graph')
    def edge(self,h,opcode,dest=None):
        v,m=one([(v,m) for v,m in self.children[h] if op(m)==opcode and (dest is None or account(self.txs[v])==dest)],'missing or ambiguous '+opcode)
        need(good(self.txs[h]) and good(self.txs[v]) and m.get('bounced') is False,'failed route edge')
        return v,m
    def incoming(self,h,opcode):
        u,m=self.parents[h]
        need(op(m)==opcode and good(self.txs[u]) and good(self.txs[h]) and m.get('bounced') is False,'invalid causal '+opcode)
        return u,m
    def bind(self,r):
        h=r['tx'];x=self.txs[h]
        need(not r['aborted'] and good(x) and lt(x)==integer(r['lt']) and integer(x['utime'])==r['time'],'indexed transfer binding')
        u,m=self.incoming(h,TRANSFER);qty=integer(r['amount_raw']);b=body(m);qid=integer(b['query_id'])
        need(qty>0 and account(self.txs[u])==r['source'] and integer(b['amount'])==qty and address(b['destination'])==r['destination'],'transfer decoded amount/owner mismatch')
        v,n=self.edge(h,INTERNAL);b=body(n)
        need(integer(b['amount'])==qty and integer(b['query_id'])==qid and address(b['from'])==r['source'],'delivery body mismatch')
        return u,v,qid

def center_pool(raw,tx):
    x=one(raw['transactions'],'historical transaction lookup')
    need(uid(x)==uid(tx) and lt(x)==lt(tx) and address(x['account'])==account(tx) and integer(x['now'])==integer(tx['utime']),'pool transaction mismatch')
    need(x.get('emulated') is False and x.get('finality')=='finalized' and x['description']['aborted'] is False,'unfinalized pool transaction')
    need(hash_id(x['account_state_before']['code_hash'])==POOL_CODE and hash_id(x['account_state_after']['code_hash'])==POOL_CODE,'unrecognized historical pool code')
    need(hash_id(x['in_msg']['hash'])==hash_id(tx['in_msg']['hash']) and x['in_msg']['opcode']==op(tx['in_msg']),'pool callback mismatch')
    return account(tx)

def inspect(tree,t):
    g=Graph(tree,t)
    return g,[h for h,x in g.txs.items() if good(x) and op(x.get('in_msg') or {}) in (JOIN,EXIT)]

def verify(t,rows,tree,pools):
    g,callbacks=inspect(tree,t);results=[]
    for h in callbacks:
        if h not in pools:continue
        x=g.txs[h];pool=center_pool(pools[h],x);opcode=op(x['in_msg'])
        sender,m=g.incoming(h,opcode);position=account(g.txs[sender]);legs=[]
        if opcode==EXIT:
            req,_=g.incoming(sender,POSITION_WITHDRAW)
            need(account(g.txs[req])==pool,'wrong withdrawal pool')
            root,_=g.incoming(req,WITHDRAW);owner=account(g.txs[root])
            need(owner not in (pool,position),'invalid withdrawal owner')
            for r in rows:
                if r['source']!=pool or r['destination']!=owner or r['aborted']:continue
                if g.parents.get(r['tx'],(None,))[0]!=h:continue
                _,v,_=g.bind(r)
                legs.append({'tx':r['tx'],'amount_raw':r['amount_raw'],'kind':'withdrawal_payout_including_possible_fees','delivery_tx':v})
            if not legs:continue
            kind='lp_withdraw'
        else:
            g.edge(h,CREDIT)
            req,_=g.incoming(sender,DEPOSIT_CREDIT)
            need(account(g.txs[req])==pool,'wrong deposit pool')
            inputs=[]
            for r in rows:
                if r['destination']!=pool or r['aborted']:continue
                _,v,qid=g.bind(r)
                n,nm=g.edge(v,NOTIFY,pool);b=body(nm)
                need(integer(b['query_id'])==qid and integer(b['amount'])==integer(r['amount_raw']) and address(b['sender'])==r['source'],'deposit notification mismatch')
                branches=[y for y,m in g.children[n] if op(m)==DEPOSIT_CREDIT and account(g.txs[y])==position and good(g.txs[y]) and m.get('bounced') is False and lt(g.txs[y])<=lt(g.txs[sender])]
                if branches:inputs.append((r,v))
            if not inputs:continue
            owner=one(list({r['source'] for r,_ in inputs}),'multiple deposit owners')
            need(owner not in (pool,position),'invalid deposit owner')
            for r,v in inputs:legs.append({'tx':r['tx'],'amount_raw':r['amount_raw'],'kind':'deposit_payment','delivery_tx':v})
            for r in rows:
                if r['source']!=pool or r['destination']!=owner or r['aborted']:continue
                if g.parents.get(r['tx'],(None,))[0]!=h:continue
                _,v,_=g.bind(r)
                legs.append({'tx':r['tx'],'amount_raw':r['amount_raw'],'kind':'deposit_associated_return','delivery_tx':v})
            kind='lp_deposit'
        results.append({'callback_tx':h,'pool':pool,'intermediate_contract':position,'owner':owner,'kind':kind,'legs':sorted(legs,key=lambda r:r['tx']),
                        'scope':'liquidity-associated JURY movement; principal, fees and position state not separated'})
    ids=[leg['tx'] for r in results for leg in r['legs']]
    need(len(ids)==len(set(ids)),'overlapping liquidity legs')
    return results

def fetch_pools(center,g,callbacks):
    result={}
    for h in callbacks:
        raw=center('transactions',{'hash':base64.b64encode(bytes.fromhex(h)).decode('ascii'),'limit':2})
        x=one(raw['transactions'],'historical transaction lookup')
        need(uid(x)==h,'wrong historical callback transaction')
        before=x['account_state_before'].get('code_hash')
        if before and hash_id(before)==POOL_CODE:result[h]=raw
    return result
