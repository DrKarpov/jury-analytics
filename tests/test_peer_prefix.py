import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from peer_prefix import start,apply,identity
from genesis_checkpoint import ANCHOR,signed
W='0:'+'a'*64
def row(lt):
    return {'lt':lt,'tx':f'{lt:064x}','previous_lt':lt-1,'previous_tx':f'{lt-1:064x}' if lt>1 else None,
            'state_before':f'{lt-1:064x}','state_after':f'{lt:064x}','time':ANCHOR+lt,
            'before':'nonexist' if lt==1 else 'active','after':'active','aborted':False,'alternate_success':True,
            'in':{'hash':'11'*32,'bounced':False}}
def fixture():
    proof={'digest':'proof','edge':{'peer':W},'target':ANCHOR+10,'counterpart':row(2)}
    return proof,start(proof)
def page(s,rows):
    return signed({'version':1,'master_digest':'md','wallet':W,'proof_digest':'proof','previous_digest':s['head'],
                   'prior':list(s['prior']),'sequence':s['pages'],'size':100,
                   'raw':{'center':{'transactions':rows},'alternate':{'transactions':rows}}})
class PeerTests(unittest.TestCase):
    def test_prefix_resume_and_identity_gate(self):
        proof,s=fixture()
        with patch('peer_prefix.compare',side_effect=lambda c,a,w:c),patch('peer_prefix.inspect_record',return_value={'owner_candidate':W}):
            first=apply(s,page(s,[row(1)]),proof,'md')
            self.assertEqual(identity(first),(None,'prefix_incomplete'))
            done=apply(first,page(first,[row(2)]),proof,'md')
            self.assertTrue(done['complete']);self.assertEqual(identity(done),({'owner_candidate':W},None))
            with self.assertRaisesRegex(ValueError,'checkpoint identity'):
                apply(done,page(done,[row(2)]),proof,'md')
    def test_missing_first_row_and_wrong_tip_rejected(self):
        proof,s=fixture()
        with patch('peer_prefix.compare',side_effect=lambda c,a,w:c),patch('peer_prefix.inspect_record',return_value={}):
            with self.assertRaisesRegex(ValueError,'predecessor gap'):
                apply(s,page(s,[row(2)]),proof,'md')
            with self.assertRaisesRegex(ValueError,'tip differs'):
                apply(s,page(s,[row(1),{**row(2),'state_after':'other'}]),proof,'md')
    def test_missing_identity_is_not_promoted(self):
        proof,s=fixture()
        with patch('peer_prefix.compare',side_effect=lambda c,a,w:c),patch('peer_prefix.inspect_record',side_effect=ValueError('missing historical code')):
            done=apply(s,page(s,[row(1),row(2)]),proof,'md')
        self.assertTrue(done['complete']);self.assertEqual(identity(done),(None,'missing historical code'))
