import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from execution_evidence import inspect
W='0:'+'a'*64
M={'hash':'11'*32,'source':'0:'+'b'*64,'destination':W,'token_opcode':'0x0f8a7ea5','bounced':False,'amount_raw':'10'}
R={'tx':'22'*32,'lt':10,'time':100,'aborted':True,'alternate_success':False,'in':M,'out':[],
   'state_before':'33'*32,'state_after':'44'*32,'code_before':'55'*32,'code_after':'55'*32}
RAW={'center':{'transactions':[{}]},'alternate':{}}
class ExecutionEvidenceTests(unittest.TestCase):
    def test_aborted_request_without_settlement_is_not_balance_proof(self):
        with patch('execution_evidence.compare',return_value=R):
            x=inspect(RAW,W,R)
        self.assertEqual(x['status'],'aborted_transfer_request_no_observed_token_settlement')
        self.assertFalse(x['state_hash_equal'])
        self.assertIn('no proven token-state delta',x['scope'])
    def test_outgoing_settlement_or_ambiguous_status_needs_more_evidence(self):
        send={**M,'source':W,'token_opcode':'0x178d4519'}
        for row in ({**R,'out':[send]},{**R,'alternate_success':None},{**R,'aborted':False},{**R,'in':{**M,'bounced':True}}):
            with patch('execution_evidence.compare',return_value=row):
                self.assertEqual(inspect(RAW,W,row)['status'],'execution_requires_state_or_message_proof')
    def test_reject_changed_observation(self):
        with patch('execution_evidence.compare',return_value={**R,'lt':11}):
            with self.assertRaisesRegex(ValueError,'differs from saved chain'):
                inspect(RAW,W,R)
