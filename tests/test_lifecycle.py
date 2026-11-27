import unittest
from test_indexer import A,B,H,row,swap,fixture
from indexer import TOKEN,MASTER,open_db,run
from lifecycle import collect,liquidity
class LifecycleTests(unittest.TestCase):
    def test_mint_burn(self):
        a={'type':'jetton_mint','action_id':H('mint'),'trace_id':H('trace'),'trace_end_utime':100,'success':True,'details':{'asset':TOKEN,'receiver':A,'amount':'100'}}
        b={'transaction_hash':H('burn'),'trace_id':H('trace2'),'transaction_now':101,'transaction_aborted':True,'jetton_master':MASTER,'owner':A,'amount':'10'}
        d=collect(lambda e,p:{'actions':[a]} if e=='actions' else {'jetton_burns':[b]},102)
        self.assertEqual(d['mints'][0]['amount_raw'],'100');self.assertTrue(d['burns'][0]['aborted'])
    def test_lp(self):
        a=swap();a['type']='dex_deposit_liquidity';a['details']={'asset_1':TOKEN,'amount_1':'1000000001','source':A,'pool':B}
        with open_db(':memory:') as db:
            d=run(db,fixture([row(1,src=A,dest=B)],[a]),cutoff=101)
            self.assertEqual(d['events'],[]);self.assertEqual(liquidity(db,101)['events'][0]['kind'],'lp_deposit')
    def test_refund_not_sell(self):
        a=swap();a['type']='dex_withdraw_liquidity';a['details']={'asset_1':TOKEN,'amount_1':'1000000001','source':A,'pool':B,'is_refund':True}
        with open_db(':memory:') as db:
            d=run(db,fixture([row(1)],[a]),cutoff=101)
            self.assertEqual(d['events'],[]);self.assertEqual(liquidity(db,101)['events'][0]['kind'],'refund')
