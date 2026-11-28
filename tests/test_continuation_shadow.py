import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from continuation_shadow import replay,capture
from genesis_checkpoint import ANCHOR,signed

W='0:'+'ab'*32
def row(lt=1,**kw):
    return {'tx':f'{lt:064x}','lt':lt,'time':ANCHOR+(lt-1),'previous_lt':lt-1,'previous_tx':f'{lt-1:064x}' if lt>1 else None,
            'state_before':f'{lt-1:064x}','state_after':f'{lt:064x}',**kw}

def fixture():
    first=row();second=row(2)
    state={'head':'head','complete':True,'prior':(1,first['tx'],first['state_after']),'rows':[first]}
    raw={'tip_center':{'transactions':[second]},'tip_alternate':{'transactions':[second]},
         'page_center':{'transactions':[second]},'page_alternate':{'transactions':[second]}}
    record={'version':1,'anchor':ANCHOR,'target':ANCHOR+10,'master_digest':'master','wallet':W,
            'base_head':'head','prior':list(state['prior']),'page_size':100,'raw':raw}
    return state,record,second

class ContinuationTests(unittest.TestCase):
    def test_replay_continues_exact_chain(self):
        state,record,second=fixture()
        with patch('continuation_shadow.compare',side_effect=lambda c,a,w:c):
            self.assertEqual(replay(signed(record),state,'master',ANCHOR+10,W),([second],True))
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                replay(signed(record),{**state,'head':'other'},'master',ANCHOR+10,W)
            with self.assertRaisesRegex(ValueError,'digest mismatch'):
                replay({**signed(record),'target':ANCHOR+11},state,'master',ANCHOR+10,W)
    def test_reject_gap_and_historical_row(self):
        state,record,second=fixture()
        with patch('continuation_shadow.compare',side_effect=lambda c,a,w:c):
            record['raw']['page_center']['transactions']=[{**second,'previous_lt':0}]
            with self.assertRaisesRegex(ValueError,'predecessor gap'):
                replay(signed(record),state,'master',ANCHOR+10,W)
            record['raw']['page_center']['transactions']=[{**second,'time':ANCHOR}]
            with self.assertRaisesRegex(ValueError,'historical gap'):
                replay(signed(record),state,'master',ANCHOR+10,W)
    def test_unchanged_tip_requires_exact_row(self):
        state,record,_=fixture();first=state['rows'][0]
        record['raw']={'tip_center':{'transactions':[first]},'tip_alternate':{'transactions':[first]},'page_center':None,'page_alternate':None}
        with patch('continuation_shadow.compare',side_effect=lambda c,a,w:c):
            self.assertEqual(replay(signed(record),state,'master',ANCHOR+10,W),([],True))
            record['raw']['tip_center']['transactions']=[{**first,'state_after':'bad'}]
            with self.assertRaisesRegex(ValueError,'unchanged tip'):
                replay(signed(record),state,'master',ANCHOR+10,W)
