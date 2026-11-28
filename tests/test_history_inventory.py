import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from history_inventory import topology,trace_inventory,wallet_inventory
from wallet_history import INTERNAL
from indexer import TOKEN

def r(tx,s,d,amount=5,aborted=False):
    return {'tx':tx,'source':s,'destination':d,'time':100,'amount_raw':str(amount),'aborted':aborted}

class InventoryTests(unittest.TestCase):
    def test_split_merge_route_and_cycle(self):
        rows=[r('1','a','b'),r('2','a','c'),r('3','b','d'),r('4','c','d'),r('5','d','a')]
        flags=topology(rows)
        for flag in ('fan_in','fan_out','chained','directed_cycle','multiple_positive_transfers'):
            self.assertIn(flag,flags)
        self.assertNotIn('directed_cycle',topology(rows[:-1]))
    def test_failed_not_counted_as_successful_edge(self):
        flags=topology([r('a','x','y'),r('b','y','x',aborted=True)])
        self.assertIn('aborted_transfer',flags)
        self.assertIn('single_positive_transfer',flags)
        self.assertNotIn('directed_cycle',flags)
    def test_all_rows_reconcile_and_unresolved_quote_retained(self):
        h=SimpleNamespace(traces={'t':[r('x','a','b'),r('y','b','c')]},events={'t':[{'kind':'buy','transfer_tx':'x'}]},
                          unresolved={'t':{'transfer_count':1,'reasons':['unclassified_trace']}},cutoff=100,head='h')
        x=trace_inventory(h)
        self.assertEqual(x['counts']['unclassified_transfer_rows'],1)
        self.assertEqual(x['review_queue'][0]['unclassified_tx'],['y'])
        h.events['t'].append({'kind':'sell','transfer_tx':'y'})
        h.unresolved['t']={'transfer_count':0,'reasons':['missing_exact_buy_quote']}
        x=trace_inventory(h)
        self.assertEqual(x['counts']['traces_requiring_review'],1)
        self.assertFalse(x['review_queue'][0]['unclassified_tx'])
    def test_wallet_unpaired_inbound_does_not_disappear(self):
        def msg(mid,source,destination):
            return {'hash':mid,'source':source,'destination':destination,'bounced':False,'token_opcode':INTERNAL,'amount_raw':'5'}
        def tx(t,lt,i,o):
            return {'tx':t,'lt':lt,'time':100,'aborted':False,'alternate_success':True,'in':i,'out':o,'code_after':'code'}
        m=msg('mint',TOKEN,'w')
        unknown=msg('missing','other','w')
        send=msg('send','w','v')
        states={'w':{'complete':True,'rows':[tx('minttx',1,m,[]),tx('unknown',2,unknown,[]),tx('sendtx',3,None,[send])]},
                'v':{'complete':True,'rows':[tx('recv',4,send,[])]}}
        p={'message':'mint','wallet':'w','recipient_tx':'minttx','amount_raw':'5'}
        x=wallet_inventory(states,{'w'},[p])
        self.assertEqual(x['matched_internal_deliveries'],1)
        self.assertEqual(x['message_counts']['mint_receipts_on_scanned_chain'],1)
        self.assertEqual(x['review_counts']['unpaired_internal_receipt'],1)
