import unittest
from test_indexer import H
from wallet_history import graph,check_rows,INTERNAL,inbound_frontier,first_page,historic_focus,choose_historical
from unittest.mock import patch

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

    def test_fresh_single_transaction_tip_reused_without_network(self):
        tip={'lt':5,'tx':H('tip'),'time':100}
        row={'lt':5,'tx':H('tip'),'time':100,'previous_lt':0,'previous_tx':None,'state_before':H('old'),'state_after':H('new')}
        with patch('wallet_history.fetch_page') as fetch:
            self.assertEqual(first_page(None,None,'wallet',tip,(0,None,None),100,row),[row])
            fetch.assert_not_called()
            with self.assertRaises(ValueError):
                first_page(None,None,'wallet',tip,(0,None,None),100,{**row,'tx':H('wrong')})
            with self.assertRaises(ValueError):
                first_page(None,None,'wallet',tip,(0,None,None),100,{**row,'previous_tx':H('wrong')})
            fetch.assert_not_called()

    def test_noninitial_tip_or_resumed_account_fetches_full_page(self):
        tip={'lt':5,'tx':H('tip'),'time':100}
        row={'lt':5,'tx':H('tip'),'time':100,'previous_lt':2,'previous_tx':H('prior')}
        with patch('wallet_history.fetch_page',return_value=['page']) as fetch:
            self.assertEqual(first_page(None,None,'wallet',tip,(0,None,None),100,row),['page'])
            fetch.assert_called_once_with(None,None,'wallet',tip,(0,None,None),100)
            fetch.reset_mock()
            self.assertEqual(first_page(None,None,'wallet',tip,(2,H('prior'),H('state')),100),['page'])
            fetch.assert_called_once_with(None,None,'wallet',tip,(2,H('prior'),H('state')),100)

    def test_historical_focus_only_current_exact_inbound(self):
        from wallet_history import ANCHOR
        from collections import defaultdict
        a,b,c=('0:'+H(k) for k in ('a','b','c'))
        mid=H('m')
        m={'source':a,'destination':b,'amount_raw':'10'}
        task={'message':mid,'peer':a,'wallet':b,'time':ANCHOR,'amount_raw':'10'}
        self.assertEqual(historic_focus([task],{mid:m},{a,c}),{a:1})
        self.assertFalse(historic_focus([{**task,'amount_raw':'9'}],{mid:m},{a,c}))
        self.assertFalse(historic_focus([task],{mid:m},{c}))
        self.assertFalse(historic_focus([task],{}, {a,c}))
        weights=defaultdict(int,{a:1,c:100})
        self.assertEqual(choose_historical([a,c],{}, {c},weights,{a:1},{},0),a)
        self.assertEqual(choose_historical([a,c],{}, {c},weights,{a:1},{},1),c)
