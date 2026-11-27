"""Exercise the actual observed twelve-transaction route and a synthetic routed variation.
Wallet Agent fixture omits decoded bodies/hashes; test augmentation is explicit,
not a claim of independently observed message payloads.
"""
import copy,unittest
from test_indexer import H
from arbitrage import evidence_records,verify
from provider import address

def fixture(routed=False):
    r=copy.deepcopy(evidence_records()[0]);r['version']=3
    w,p,q=map(address,(r['owner'],r['first'],r['second']))
    a={'trace':r['trace'],'time':r['time'],'tx':'4d31debceef3c4708cee9a9415a52350dab76bc38f139fb6935f911c1cf56fa3','lt':'119463478000049','source':p,'destination':w,'amount_raw':'26094683475','aborted':False}
    b={**a,'tx':'b3289a10e194683e2fb21a575b441fc1706c5664e859b471a26aa6a6d765a588','lt':'119463478000055','source':w,'destination':q}
    sale={'kind':'sell','transfer_tx':b['tx'],'wallet':w,'quote_asset':'GRAM','quote_raw':'7209799513','time':r['time']}
    txs=sorted(r['transactions'],key=lambda x:int(x['lt']))
    for x in txs:x['account']=address(x['account'])
    for x in txs:
        for m in x['messages']:m['counterparty']=address(m['counterparty'])
    if routed:
        root=txs[0];first=root['messages'][0];value=first['amount_gram']['raw'];router='0:'+'a'*64
        first['counterparty']=router;first['opcode']='0xea06185d';first['body']={'amount':'7200000000'}
        pool=next(x for x in txs if x['account']==p);pool['messages'][0]['counterparty']=router
        txs.append({'hash':H('router'),'account':router,'lt':str(int(root['lt'])+1),'time':r['time'],'success':True,'fee_gram':{'raw':'1'},'messages':[{'direction':'in','counterparty':w,'amount_gram':{'raw':value},'opcode':'0xea06185d','bounced':False,'body':{'amount':'7200000000'}},{'direction':'out','counterparty':p,'amount_gram':{'raw':value},'opcode':'0xfa45056b','bounced':False}]})
    for x in txs:
        for m in x['messages']:
            if m['direction']!='out':continue
            y,n=next((y,n) for y in txs if int(y['lt'])>int(x['lt']) and y['account']==m['counterparty'] for n in y['messages'] if n['direction']=='in' and n['counterparty']==x['account'] and n['opcode']==m['opcode'] and n['amount_gram']['raw']==m['amount_gram']['raw'])
            m['message_hash']=n['message_hash']=H(x['hash']+y['hash']+m['opcode'])
            opcode=m['opcode'];idx=1 if int(x['lt'])<int(b['lt']) and (x['account']!=w or opcode!='0x0f8a7ea5') else 2
            body=m.get('body',{})
            if opcode=='0x0f8a7ea5':
                idx=1 if x['account']==p else 2;body={'amount':a['amount_raw'],'query_id':str(idx),'destination':w if idx==1 else q}
            elif opcode=='0x178d4519':body={'amount':a['amount_raw'],'query_id':str(idx),'from':p if idx==1 else w}
            elif opcode=='0x7362d09c':body={'amount':a['amount_raw'],'query_id':str(idx),'sender':p if idx==1 else w}
            m['body']=n['body']=body
    r['transactions']=txs
    return r,a,b,sale

class RouteProof(unittest.TestCase):
    def test_direct(self):
        r,a,b,s=fixture()
        buy,c=verify(r,[a,b],[s]);self.assertEqual(c['native_net_raw'],'36279491');self.assertEqual(buy['quote_status'],'unresolved')
    def test_router(self):
        r,a,b,s=fixture(True)
        buy,c=verify(r,[a,b],[s]);self.assertEqual(buy['quote_raw'],'7200000000');self.assertEqual(c['native_net_raw'],'36279491')
    def test_bad_amount(self):
        r,a,b,s=fixture()
        for x in r['transactions']:
            for m in x['messages']:
                if m['opcode']=='0x178d4519':m['body']['amount']='1'
        with self.assertRaises(ValueError):verify(r,[a,b],[s])
    def test_missing_message(self):
        r,a,b,s=fixture();r['transactions'].pop()
        with self.assertRaises(ValueError):verify(r,[a,b],[s])
