import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from master_continuation import base_state,messages_from
from genesis_checkpoint import ANCHOR,signed
from indexer import TOKEN
W='0:'+'a'*64
class MasterContinuationTests(unittest.TestCase):
    def test_base_binds_legacy_tip(self):
        row={'tx':'11'*32,'lt':10,'time':ANCHOR,'state_after':'22'*32}
        legacy={'tx':row['tx'],'lt':10,'time':ANCHOR}
        master={'digest':'md','transactions':[{**legacy,'outbound':[],'in_opcode':None}]}
        raw={'center':{'transactions':[{'in_msg':None}]},'alternate':{}}
        rec=signed({'version':1,'anchor':ANCHOR,'master_digest':'md','raw':raw})
        with patch('master_continuation.identity',return_value=legacy),patch('master_continuation.outbound',return_value={}),patch('master_continuation.compare',return_value=row):
            state=base_state(rec,master)
            self.assertEqual(state['prefix']['prior'],(10,row['tx'],row['state_after']))
            self.assertEqual(state['prefix']['head'],rec['digest'])
            with self.assertRaisesRegex(ValueError,'anchor transaction mismatch'):
                base_state(rec,{**master,'transactions':[{**master['transactions'][0],'lt':11}]})
    def test_outbound_only_successful_and_exact(self):
        m={'hash':'33'*32,'source':TOKEN,'destination':W,'amount_raw':'9','bounced':False,'token_opcode':'0x178d4519'}
        row={'tx':'11'*32,'lt':10,'time':ANCHOR+1,'aborted':False,'alternate_success':True,'out':[m]}
        messages,unknown=messages_from([row])
        self.assertEqual(messages[m['hash']]['amount_raw'],'9')
        self.assertEqual(messages[m['hash']]['wallet'],W)
        self.assertEqual(unknown,{})
        self.assertEqual(messages_from([{**row,'aborted':True}]),({}, {'failed_or_bounced':1}))
        self.assertEqual(messages_from([{**row,'out':[{**m,'amount_raw':None}]}]),({}, {'unsupported_outbound':1}))
        with self.assertRaisesRegex(ValueError,'duplicate master'):
            messages_from([row,row])
