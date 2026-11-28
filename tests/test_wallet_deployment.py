import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wallet_deployment import activation,replay,code_observation,capture

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
        r=row();raw={'center':{'transactions':[{'account_state_after':{'code_hash':'33'*32}}]},'alternate':{}}
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

    def test_fallback_replays_exact_account_row_without_splicing(self):
        r=row()
        calls=[]
        def center(ep,params):
            calls.append((ep,params))
            return {'transactions':[{'marker':ep}]}
        def alternate(ep,params):
            if '/messages/' in ep:return {'marker':'message'}
            return {'transactions':[{'marker':'account'}]}
        attempts=[]
        with patch('wallet_deployment.replay',side_effect=[ValueError('missing hash'),{'code_hash':'33'*32}]) as check:
            raw,initial=capture(W,r,center,alternate,attempts)
        self.assertEqual(initial,{'code_hash':'33'*32})
        self.assertEqual(raw,{'center':{'transactions':[{'marker':'transactions'}]},'alternate':{'marker':'account'}})
        self.assertEqual([x['method'] for x in attempts],['message','account_lt'])
        self.assertEqual(attempts[0]['error'],'missing hash')
        self.assertEqual(calls[1][1]['start_lt'],r['lt'])
        self.assertEqual(calls[1][1]['end_lt'],r['lt'])
        self.assertEqual(check.call_count,2)

    def test_missing_historical_code_is_not_treated_as_confirmed(self):
        r=row();raw={'center':{'transactions':[{'account_state_after':{'code_hash':None}}]},'alternate':{}}
        with patch('wallet_deployment.compare',return_value=r),patch('wallet_deployment.inspect_record') as inspect:
            with self.assertRaisesRegex(ValueError,'code_after hash missing'):replay(W,r,raw)
            inspect.assert_not_called()
