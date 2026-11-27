import unittest
from test_indexer import H
from wallet_history import graph,check_rows,INTERNAL

class WalletHistoryTests(unittest.TestCase):
    def test_predecessor_and_state_gap(self):
        tip={'lt':5,'tx':H('tx')}
        r={'lt':5,'tx':H('tx'),'time':100,'previous_lt':0,'previous_tx':None,'state_before':H('old'),'state_after':H('new')}
        self.assertEqual(check_rows([r],(0,None,None),tip),(5,H('tx'),H('new')))
        with self.assertRaises(ValueError):check_rows([r],(1,H('prior'),H('state')),tip)
    def test_only_successful_matched_receipt_expands_graph(self):
        a,b,c=('0:'+H(k) for k in ('a','b','c'))
        m={'hash':H('m'),'source':a,'destination':b,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'10'}
        n={**m,'hash':H('n'),'source':b,'destination':c}
        sender={'lt':1,'aborted':False,'alternate_success':True,'in':None,'out':[m]}
        target={'lt':2,'aborted':True,'alternate_success':False,'in':m,'out':[n]}
        states={a:{'rows':[sender]},b:{'rows':[target]}}
        linked,candidates,edges,matched=graph(states,{a})
        self.assertEqual(linked,{a});self.assertEqual(candidates,{a,b});self.assertFalse(matched)
        target.update(aborted=False,alternate_success=True)
        linked,candidates,edges,matched=graph(states,{a})
        self.assertEqual(linked,{a,b});self.assertEqual(candidates,{a,b,c});self.assertEqual(matched,{m['hash']})
