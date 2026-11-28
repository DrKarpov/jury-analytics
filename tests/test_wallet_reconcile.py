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

    def test_unlinked_failed_recipient_is_observed_not_missing(self):
        a,b=('0:'+H(k) for k in ('a','b'))
        m={'hash':H('m'),'source':a,'destination':b,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'10'}
        s={'tx':H('s'),'lt':1,'time':100,'aborted':False,'alternate_success':True,'in':None,'out':[m]}
        q={'tx':H('q'),'lt':2,'time':101,'aborted':True,'alternate_success':False,'in':m,'out':[]}
        states={a:{'rows':[s],'complete':True},b:{'rows':[q],'complete':True}}
        r=compare_history(states,{a},[],{})
        self.assertEqual(r['unmatched_reason_counts'],{'recipient_failed_or_unknown_transaction':1})
        self.assertEqual(r['linked_accounts'],1)
        q['in']={**m,'amount_raw':'9'}
        self.assertEqual(compare_history(states,{a},[],{})['unmatched_reason_counts'],{'recipient_message_fields_differ':1})

    def test_upstream_gap_in_scanned_prefix(self):
        a,b=('0:'+H(k) for k in ('a','b'))
        m={'hash':H('m'),'source':a,'destination':b,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'10'}
        q={'tx':H('q'),'lt':2,'time':101,'aborted':False,'alternate_success':True,'in':m,'out':[]}
        states={a:{'rows':[],'complete':False,'prior':(3,H('other'),None)},b:{'rows':[q],'complete':True}}
        r=compare_history(states,{b},[],{})
        self.assertEqual(r['unmatched_inbound_reason_counts'],{'sender_missing_in_scanned_prefix':1})

    def test_primary_and_receipt_census(self):
        a,b=('0:'+H(k) for k in ('a','b'))
        m={'hash':H('m'),'source':a,'destination':b,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'10'}
        s={'tx':H('s'),'lt':1,'time':100,'aborted':False,'alternate_success':True,'in':None,'out':[m]}
        q={'tx':H('q'),'lt':2,'time':101,'aborted':False,'alternate_success':True,'in':m,'out':[]}
        other={'tx':H('other'),'lt':3,'time':102,'aborted':False,'alternate_success':True,'in':None,'out':[]}
        states={a:{'rows':[s,other],'complete':True},b:{'rows':[q],'complete':True}}
        idx={h:{'tx':h,'time':100,'amount_raw':'10','aborted':False} for h in (s['tx'],other['tx'],H('unseen'))}
        receipt={'wallet':b,'message':m['hash'],'recipient_tx':q['tx'],'recipient_lt':'2','amount_raw':'10'}
        pending={'wallet':'0:'+H('pending'),'message':H('p'),'recipient_tx':H('pt'),'recipient_lt':'3','amount_raw':'1'}
        r=compare_history(states,{a},[receipt,pending],idx)
        self.assertEqual(r['primary_coverage_counts'],{'matched_endpoint_hash_amount':1,'observed_hash_not_matched_endpoint':1,'hash_not_observed_on_linked_chain':1})
        self.assertEqual(r['master_receipt_chain_counts'],{'observed_on_chain':1,'chain_not_yet_scanned_to_receipt':1})
