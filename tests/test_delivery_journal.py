import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from canonical_movements import Observations
from delivery_journal import build,preserve,signed_delta,repair_plan
from genesis_checkpoint import ANCHOR
from indexer import TOKEN,integer
A='0:'+'a'*64
B='0:'+'b'*64
def msg(mid,src,dst,amount):
    return {'hash':mid,'source':src,'destination':dst,'amount_raw':str(amount),'bounced':False,'token_opcode':'0x178d4519'}
def row(tx,lt,ins,outs):
    return {'tx':tx,'lt':lt,'time':ANCHOR,'aborted':False,'alternate_success':True,'in':ins,'out':outs}
M=msg('11'*32,TOKEN,A,100)
N=msg('22'*32,A,B,30)
R=row('33'*32,2,M,[])
S=row('44'*32,3,None,[N])
T=row('55'*32,4,N,[])
E={M['hash']:{'message':M['hash'],'wallet':A,'amount_raw':'100','master_tx':'66'*32,'master_lt':1,'master_at':ANCHOR,'master_aborted':False}}
P={M['hash']:{'message':M['hash'],'wallet':A,'amount_raw':'100','recipient_tx':R['tx'],'recipient_lt':2,'recipient_at':ANCHOR}}
def obs(items):
    o=Observations();o.ingest(items);return o
class DeliveryJournalTests(unittest.TestCase):
    def test_pair_and_distribution_replay(self):
        items=[(A,R),(A,S),(B,T)]
        x=build(obs(items),{A},E,P,ANCHOR)
        y=build(obs(list(reversed(items))+items),{A},E,P,ANCHOR)
        self.assertEqual(x,y);self.assertEqual(x['journal_entry_count'],4)
        self.assertEqual(x['wallet_net_raw'],{A:'70',B:'30'})
        self.assertEqual(x['master_distribution_raw'],'100')
        self.assertEqual(x['unresolved_counts'],{})
    def test_unpaired_not_guessed_and_later_pair_preserves_postings(self):
        x=build(obs([(A,R),(A,S)]),{A},E,P,ANCHOR)
        self.assertEqual(x['wallet_net_raw'],{A:'100'})
        self.assertEqual(x['unresolved_counts'],{'unpaired_internal_outgoing':1})
        y=build(obs([(A,R),(A,S),(B,T)]),{A},E,P,ANCHOR)
        preserve(x,y)
        self.assertEqual(y['unresolved_counts'],{})
    def test_missing_master_prefix_and_burn_not_promoted(self):
        x=build(obs([(A,S),(B,T)]),{A},E,P,ANCHOR)
        self.assertEqual(x['master_deliveries_posted'],0)
        self.assertEqual(x['wallets_with_negative_ending_net'],1)
        self.assertEqual(x['unresolved_counts']['master_delivery_unposted'],1)
        burn={**N,'token_opcode':'0x595f07bc'}
        x=build(obs([(A,R),(A,{**S,'out':[burn]})]),{A},E,P,ANCHOR)
        self.assertEqual(x['journal_entry_count'],2)
        self.assertEqual(x['unresolved_counts'],{'burn_semantics_unverified':1})

    def test_signed_postings_keep_external_amount_validation_strict(self):
        for value,expected in [('0',0),('-30',-30),('30',30),('-900719925474099312345',-900719925474099312345)]:
            self.assertEqual(signed_delta(value),expected)
        for value in (True,False,None,1,-1,1.5,'','-0','01','-01','+1','1.0','1e3',' 1','1\n','١'):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'invalid signed journal delta'):
                signed_delta(value)
        with self.assertRaisesRegex(ValueError,'invalid amount'):
            integer('-30')
        invalid={**E[M['hash']],'amount_raw':'-100'}
        with self.assertRaisesRegex(ValueError,'invalid amount'):
            build(obs([(A,R)]),{A},{M['hash']:invalid},P,ANCHOR)
    def test_negative_partial_net_is_not_lost_or_clamped(self):
        x=build(obs([(A,S),(B,T)]),{A},E,P,ANCHOR)
        self.assertEqual(x['wallet_net_raw'],{A:'-30',B:'30'})
        self.assertEqual(x['negative_running_minima_raw'],{A:'-30'})
        self.assertEqual(x['accounted_wallet_net_raw'],'0')

    def test_repair_plan_routes_without_posting(self):
        s={**S,'time':ANCHOR+1}
        o=obs([(A,R),(A,s)])
        result=build(o,{A},E,P,ANCHOR+1)
        before=result['journal']
        plan=repair_plan(result,o,ANCHOR,{B:{'complete':True,'rows':[T]}},{},{},{})
        self.assertEqual(plan['route_counts'],{'start_regular_cursor':1})
        self.assertEqual(plan['tasks'][0]['peer'],B)
        self.assertEqual(plan['tasks'][0]['message'],N['hash'])
        self.assertEqual(result['journal'],before)
        plan=repair_plan(result,o,ANCHOR,{}, {}, {}, {})
        self.assertEqual(plan['route_counts'],{'capture_exact_counterpart':1})
        historic=build(obs([(A,R),(A,S)]),{A},E,P,ANCHOR)
        self.assertEqual(repair_plan(historic,obs([(A,R),(A,S)]),ANCHOR,{}, {}, {}, {})['route_counts'],
                         {'historical_message_closure':1})
