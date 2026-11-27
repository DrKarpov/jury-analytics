import unittest
from test_indexer import H
from wallet_reconcile import compare_history
from wallet_history import INTERNAL

class ReconcileTests(unittest.TestCase):
    def test_exact_message_and_hash_comparison_does_not_invent_owner(self):
        a,b=('0:'+H(k) for k in ('a','b'))
        m={'hash':H('m'),'source':a,'destination':b,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'10'}
        s={'tx':H('s'),'lt':1,'time':100,'aborted':False,'alternate_success':True,'in':None,'out':[m]}
        t={'tx':H('t'),'lt':2,'time':101,'aborted':False,'alternate_success':True,'in':m,'out':[]}
        states={a:{'rows':[s],'complete':True},b:{'rows':[t],'complete':True}}
        idx={s['tx']:{'tx':s['tx'],'time':100,'amount_raw':'10','aborted':False}}
        r=compare_history(states,{a},[],idx)
        self.assertEqual(r['matched_deliveries'],1)
        self.assertEqual(r['matched_status_counts'],{'hash_amount_agree':1})
        self.assertEqual(r['index_hash_amount_candidates'],1)
        r=compare_history(states,{a},[],{})
        self.assertEqual(r['matched_status_counts'],{'not_found_by_either_endpoint_tx_hash':1})
    def test_receipt_gap_and_unmatched_recipient(self):
        a,b=('0:'+H(k) for k in ('a','b'))
        m={'hash':H('m'),'source':a,'destination':b,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'10'}
        s={'tx':H('s'),'lt':1,'time':100,'aborted':False,'alternate_success':True,'in':None,'out':[m]}
        states={a:{'rows':[s],'complete':True}}
        proof={'wallet':a,'message':H('root'),'recipient_tx':H('absent'),'recipient_lt':'1','amount_raw':'9'}
        r=compare_history(states,{a},[proof],{})
        self.assertEqual(len(r['master_receipt_chain_gaps']),1)
        self.assertEqual(r['unmatched_reason_counts'],{'recipient_not_scanned':1})
