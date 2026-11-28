import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from canonical_movements import Observations
from wallet_history import INTERNAL

A='0:'+'aa'*32
B='0:'+'bb'*32
def fixture():
    m={'hash':'11'*32,'source':A,'destination':B,'amount_raw':'10','bounced':False,'token_opcode':INTERNAL}
    s={'tx':'22'*32,'lt':1,'time':1,'aborted':False,'alternate_success':True,'in':None,'out':[m]}
    r={'tx':'33'*32,'lt':2,'time':2,'aborted':False,'alternate_success':True,'in':m,'out':[]}
    return s,r

class CanonicalMovementsTests(unittest.TestCase):
    def test_batch_arrival_and_retries(self):
        s,r=fixture();a=Observations();a.ingest([(A,s),(B,r)])
        b=Observations();b.ingest([(B,r)])
        self.assertEqual(b.project({A})['matched_deliveries'],0)
        b.ingest([(A,s),(B,r),(A,s)])
        x=a.project({A})
        self.assertEqual(x,b.project({A}))
        self.assertEqual(x['matched_deliveries'],1)
        self.assertEqual(x['events'][0]['id'],'11'*32)
        self.assertEqual(x['net_internal_movements_raw'],{A:'-10',B:'10'})
    def test_conflicting_duplicate_is_rejected(self):
        s,r=fixture();a=Observations();a.ingest([(A,s)])
        with self.assertRaisesRegex(ValueError,'conflicting'):a.ingest([(A,{**s,'lt':3})])
        with self.assertRaisesRegex(ValueError,'conflicting'):a.ingest([(B,s)])
    def test_failed_wrong_amount_and_wrong_lt_are_not_movements(self):
        s,r=fixture()
        for bad in ({**r,'aborted':True},{**r,'in':{**r['in'],'amount_raw':'9'}},{**r,'lt':1}):
            with self.subTest(bad=bad):
                a=Observations();a.ingest([(A,s),(B,bad)])
                x=a.project({A});self.assertEqual(x['events'],[]);self.assertEqual(x['net_internal_movements_raw'],{})
