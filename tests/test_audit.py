import unittest
from test_indexer import A,B,H,row,swap,fixture
from indexer import TOKEN,MASTER,open_db,run
from audit import compare,holders_api,holder_snapshot,tonapi_swaps

def event(trace=1, amount='1000000001', gram=2000000000):
    return {'event_id':H('t'+str(trace)),'in_progress':False,'actions':[{'type':'JettonSwap','status':'ok','JettonSwap':{'jetton_master_out':{'address':TOKEN},'amount_out':amount,'gram_in':gram,'user_wallet':{'address':A}}}]}
def center_holders(endpoint, params):
    if endpoint == 'jetton/masters':
        return {'jetton_masters': [{'address': MASTER, 'total_supply': '10'}]}
    return {'jetton_wallets': [{'address': B, 'owner': A, 'jetton': MASTER, 'balance': '10'}]}

def alternate_holders(endpoint, params):
    if endpoint.endswith('/holders'):
        return {'addresses': [{'address': B, 'owner': {'address': A}, 'balance': '10'}], 'total': 1}
    return {'metadata': {'address': MASTER, 'decimals': '9'}, 'total_supply': '10'}

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.db=open_db(':memory:');self.data=run(self.db,fixture([row(1)],[swap()]),cutoff=101)
    def tearDown(self): self.db.close()
    def test_match(self):self.assertEqual(compare(self.data,lambda e,p:event())['status'],'discovered_trace_swaps_match')
    def test_amount_mismatch(self):self.assertEqual(compare(self.data,lambda e,p:event(gram=1))['status'],'mismatch')
    def test_pending(self):self.assertEqual(compare(self.data,lambda e,p:{**event(),'in_progress':True})['status'],'unavailable')
    def test_malformed_empty_actions_are_unavailable(self):
        with self.assertRaisesRegex(ValueError,'event actions'):
            tonapi_swaps({**event(), 'actions': {}}, H('t1'))
    def test_wrong_identity(self):self.assertEqual(compare(self.data,lambda e,p:event(2))['status'],'unavailable')
    def test_missing_primary_swap(self):
        d=run(self.db,fixture([row(1)],[swap()]),cutoff=101);d['events']=[];d['unresolved']=[{'trace':H('t1')}];self.assertEqual(compare(d,lambda e,p:event())['status'],'mismatch')
    def test_raw_transfer(self):self.assertEqual(self.data['transfers'][0]['amount_raw'],'1000000001')
    def test_holders(self):
        self.assertEqual(holder_snapshot(center_holders, alternate_holders)['owners'],[{'owner':A,'balance_raw':'10'}])
    def test_supply_mismatch(self):
        def center(endpoint, params):
            if endpoint == 'jetton/masters':
                return {'jetton_masters': [{'address': MASTER, 'total_supply': '11'}]}
            return center_holders(endpoint, params)
        with self.assertRaisesRegex(ValueError,'supply'):
            holder_snapshot(center, alternate_holders)
    def test_decimals_mismatch(self):
        def alternate(endpoint, params):
            if endpoint.endswith('/holders'):
                return alternate_holders(endpoint, params)
            return {'metadata': {'address': MASTER, 'decimals': '6'}, 'total_supply': '10'}
        with self.assertRaisesRegex(ValueError,'decimals'):
            holder_snapshot(center_holders, alternate)
    def test_holder_count_mismatch(self):
        with self.assertRaises(ValueError):holders_api(lambda e,p:{'addresses':[],'total':1})
    def test_full_re_read(self):
        db=open_db(':memory:');calls=0
        def f(e,p):
            nonlocal calls
            calls+=1;return fixture([row(1)] if calls==1 else [],[swap()])(e,p)
        with self.assertRaises(ValueError):run(db,f,cutoff=101,full=True)
        db.close()
if __name__=='__main__':unittest.main()
