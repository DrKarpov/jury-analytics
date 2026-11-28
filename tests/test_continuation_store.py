import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from continuation_store import cursor,apply,next_target
from genesis_checkpoint import ANCHOR

W='0:'+'ab'*32
def row(lt):
    return {'lt':lt,'tx':f'{lt:064x}','state_after':f'{lt:064x}'}
def base():
    first=row(1);return {'complete':True,'rows':[first],'prior':(1,first['tx'],first['state_after']),'head':'base'}
def rec(target,head='next'):
    return {'target':target,'digest':head,'observed_at':target+10,'raw':{'tip_center':{'transactions':[{}]},'tip_alternate':{'transactions':[{}]}}}
class PersistentContinuationTests(unittest.TestCase):
    def test_partial_page_continues_same_pinned_tip(self):
        c=cursor(base());target=ANCHOR+10
        with patch('continuation_store.replay',return_value=([row(2)],False)),patch('wallet_history.compare',return_value=row(3)):
            p=apply(c,rec(target),W,'master')
        self.assertFalse(p['tip_reached']);self.assertEqual(p['prefix']['prior'][0],2)
        self.assertEqual(next_target(p,target+100),target)
        with patch('continuation_store.replay',return_value=([row(3)],True)),patch('wallet_history.compare',return_value=row(3)):
            q=apply(p,rec(target,'next2'),W,'master')
        self.assertTrue(q['tip_reached']);self.assertEqual(q['new_rows'],[row(2),row(3)])
        self.assertEqual(q['prefix']['head'],'next2');self.assertEqual(next_target(q,target+100),target+100)
        self.assertIsNone(next_target(q,target))
    def test_target_and_tip_change_rejected(self):
        c=cursor(base());target=ANCHOR+10
        with patch('continuation_store.replay',return_value=([row(2)],False)),patch('wallet_history.compare',return_value=row(3)):
            p=apply(c,rec(target),W,'master')
        with self.assertRaisesRegex(ValueError,'unfinished pinned target'):
            apply(p,rec(target+1),W,'master')
        with patch('continuation_store.replay',return_value=([row(3)],True)),patch('wallet_history.compare',return_value=row(4)):
            with self.assertRaisesRegex(ValueError,'pinned tip changed'):
                apply(p,rec(target),W,'master')
    def test_completed_target_no_duplicate_or_rollback(self):
        c=cursor(base());target=ANCHOR+10
        with patch('continuation_store.replay',return_value=([],True)),patch('wallet_history.compare',return_value=row(1)):
            p=apply(c,rec(target),W,'master')
            with self.assertRaisesRegex(ValueError,'duplicate completed target'):
                apply(p,rec(target),W,'master')
        with self.assertRaisesRegex(ValueError,'target rollback'):
            apply(p,rec(target-1),W,'master')
