import unittest
from test_indexer import H
from wallet_history import graph,check_rows,INTERNAL,inbound_frontier

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

    def test_backward_discovery_requires_exact_successful_sender(self):
        a,b=('0:'+H(k) for k in ('upstream','root'))
        m={'hash':H('inbound'),'source':a,'destination':b,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'10'}
        recv={'lt':2,'aborted':False,'alternate_success':True,'in':m,'out':[]}
        states={b:{'rows':[recv]}}
        linked,candidates,edges,matched=graph(states,{b})
        self.assertEqual(linked,{b});self.assertEqual(candidates,{a,b})
        self.assertEqual(set(inbound_frontier(states,linked,matched)),{m['hash']})
        send={'lt':1,'aborted':False,'alternate_success':True,'in':None,'out':[{**m,'amount_raw':'9'}]}
        states[a]={'rows':[send]}
        self.assertEqual(graph(states,{b})[0],{b})
        send['out']=[m];send['lt']=3
        self.assertEqual(graph(states,{b})[0],{b})
        send['lt']=1;send['aborted']=True
        self.assertEqual(graph(states,{b})[0],{b})
        send['aborted']=False
        linked,candidates,edges,matched=graph(states,{b})
        self.assertEqual(linked,{a,b});self.assertEqual(matched,{m['hash']})
        self.assertEqual(set(edges),matched)
        self.assertFalse(inbound_frontier(states,linked,matched))

    def test_master_not_scanned_as_wallet(self):
        from indexer import TOKEN
        b='0:'+H('root')
        m={'hash':H('mint'),'source':TOKEN,'destination':b,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'10'}
        states={b:{'rows':[{'lt':2,'aborted':False,'alternate_success':True,'in':m,'out':[]}]}}
        linked,candidates,edges,matched=graph(states,{b})
        self.assertEqual(candidates,{b});self.assertFalse(inbound_frontier(states,linked,matched))
