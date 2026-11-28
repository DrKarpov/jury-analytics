import unittest
from unittest.mock import patch
from test_indexer import H
from genesis_checkpoint import signed, validate_master, capture_receipt, validate_receipt, ANCHOR, DEPLOYMENT, DEPLOYMENT_LT
from indexer import MASTER,TOKEN

class GenesisCheckpointTests(unittest.TestCase):
    def master(self):
        return signed({'version':1,'token':MASTER,'cutoff':ANCHOR,'transactions':[
            {'tx':DEPLOYMENT,'lt':DEPLOYMENT_LT,'previous_lt':0,'previous_tx':None,'time':ANCHOR-100,'before':'nonexist','after':'active','aborted':False,'outbound':[
                {'message':H('message'),'wallet':'0:'+H('wallet'),'amount_raw':'500'}]}]})
    def test_validate_master_and_reject_rewritten_chain(self):
        r=self.master();self.assertEqual(len(validate_master(r)),1)
        r['transactions'][0]['lt']+=1
        with self.assertRaises(ValueError):validate_master(r)
    def test_receipt_replay_and_wrong_master(self):
        m=self.master();msg=next(iter(validate_master(m).values()));core={k:msg[k] for k in ('message','wallet','amount_raw')}
        proof={**core,'recipient_tx':H('recipient'),'recipient_lt':str(DEPLOYMENT_LT+1),'recipient_at':ANCHOR-99}
        def replay(c,a,msg,**kwargs):
            self.assertEqual(c('x',{}),{'primary':1});self.assertEqual(a('y',{}),{'alternate':2})
            return proof
        with patch('genesis_checkpoint.receipt',side_effect=replay):
            r=capture_receipt(lambda e,p:{'primary':1},lambda e,p:{'alternate':2},msg,m['digest'])
            self.assertEqual(validate_receipt(r,msg,m['digest']),proof)
            with self.assertRaises(ValueError):validate_receipt(r,msg,H('other'))
