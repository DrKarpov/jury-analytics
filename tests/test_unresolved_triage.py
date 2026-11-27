import unittest
from unresolved_triage import profile,raw_summary
T='a'*64
class TriageTests(unittest.TestCase):
    def test_actions(self):
        def a(t,success=True,**d):return {'type':t,'success':success,'details':d}
        self.assertEqual(profile([a('jetton_transfer')])['group'],'transfer_actions_only')
        self.assertEqual(profile([a('dex_withdraw_liquidity',is_refund=True)])['group'],'refund_action_present')
        self.assertEqual(profile([a('jetton_swap',dex='mooncx_clmm'),a('dex_deposit_liquidity')])['group'],'mixed_swap_lp')
        self.assertEqual(profile([a('jetton_swap',False)])['group'],'failed_or_unknown_actions')
        self.assertEqual(profile([])['group'],'no_provider_actions')
    def test_raw_hints_not_protocol_proof(self):
        tree={'transaction':{'hash':T,'account':{'address':'0:'+'b'*64},'in_msg':{'op_code':'0x123'}},'interfaces':['moon_pool']}
        s=raw_summary(tree,T,[{'tx':T}])
        self.assertEqual(len(s['moon_provider_hints']),1)
        with self.assertRaises(ValueError):raw_summary(tree,T,[{'tx':'c'*64}])
