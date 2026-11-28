import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wallet_deployment import activation,replay,code_observation

W='0:'+'ab'*32
def row(**updates):
    r={'tx':'11'*32,'lt':1,'before':'nonexist','after':'active','aborted':False,'alternate_success':True,
       'in':{'hash':'22'*32,'destination':W,'bounced':False},'code_after':'33'*32}
    return {**r,**updates}

class DeploymentTests(unittest.TestCase):
    def test_activation_requires_success_and_unique_transition(self):
        r=row()
        self.assertEqual(activation({'rows':[r]}),(r,None))
        self.assertEqual(activation({'rows':[row(aborted=True)]})[1],'activation_not_observed')
        self.assertEqual(activation({'rows':[r,row(lt=2)]})[1],'multiple_activations')
        self.assertEqual(activation({'rows':[row(before='frozen')]})[1],'unsupported_activation_status')
    def test_replay_requires_exact_checkpoint_row(self):
        r=row();raw={'center':{'transactions':[{}]},'alternate':{}}
        with patch('wallet_deployment.compare',return_value={**r,'lt':2}),patch('wallet_deployment.inspect_record') as inspect:
            with self.assertRaisesRegex(ValueError,'saved chain'):replay(W,r,raw)
            inspect.assert_not_called()
        with patch('wallet_deployment.compare',return_value=r),patch('wallet_deployment.inspect_record',return_value={'code_hash':'33'*32}) as inspect:
            self.assertEqual(replay(W,r,raw),{'code_hash':'33'*32})
            inspect.assert_called_once_with({'raw':raw},{'wallet':W,'message':r['in']['hash'],'recipient_tx':r['tx']})
    def test_code_observations_do_not_hide_gaps(self):
        r=row()
        result=code_observation({'rows':[r,row(code_after=None),row(code_after='44'*32),row(after='nonexist',code_after=None)],'complete':False},{'code_hash':'33'*32})
        self.assertEqual(result,{'active_rows':3,'different_code_rows':1,'missing_code_rows':1,'inactive_rows':1,'chain_complete':False})
