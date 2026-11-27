import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from repair_overlay import verify,overlay,RULE
from repair_alias import propose,swaps
from test_alias import AliasTests
from test_indexer import H
from indexer import classify,digest,publish,MASTER
from incremental import History
from recovery import recover

class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Path(self.tmp.name);self.trace=H('t1')
        a,rows=AliasTests().scenario('buy');self.rows=rows
        before,u=classify(self.trace,[a],rows,101,allow_alias=False)
        after,_=classify(self.trace,[a],rows,101)
        e=after[0]
        event={'event_id':self.trace,'in_progress':False,'actions':[{'type':'JettonSwap','status':'ok','JettonSwap':{'jetton_master_out':{'address':a['details']['asset_out']},'amount_out':e['amount_raw'],'gram_in':e['quote_raw'],'user_wallet':{'address':e['wallet']}}}]}
        self.seed={'schema':2,'token':MASTER,'cutoff':101,'transfer_count':1,'trace_count':1,'transfers':rows,'events':before,'unresolved':[u]}
        self.seed['digest']=digest(self.seed)
        self.record={'version':1,'rule':RULE,'seed_digest':self.seed['digest'],'trace':self.trace,'before_events':before,'before_unresolved':u,'transfer_digest':digest(rows),'center_actions':[a],'alternate_event':event,'proposal':propose(self.trace,[a],rows,before,u,101,swaps(after))}
        self.record['digest']=digest(self.record)
        self.ctx=({self.trace:rows},{self.trace:before},{self.trace:u},{self.trace:{'primary_swaps':[],'alternate_swaps':[[list(k),v] for k,v in swaps(after).items()]}})
        self.folder=self.store/'repairs'/RULE;self.folder.mkdir(parents=True);publish(self.record,self.folder/(self.trace+'.json'))
    def tearDown(self):self.tmp.cleanup()
    def test_verify(self):self.assertEqual(verify(self.record,self.seed,self.ctx)['added'],1)
    def test_reject_tampered(self):
        self.record['proposal']['added']=2
        with self.assertRaises(ValueError):verify(self.record,self.seed,self.ctx)
    def test_overlay_idempotent(self):
        h=History(self.seed)
        with patch('repair_overlay.contexts',return_value=self.ctx):
            a=overlay(self.store,self.seed,h);b=overlay(self.store,self.seed,h)
        self.assertEqual(a['applied'],1);self.assertEqual(b['already_present'],1)
        self.assertEqual(h.candidate()['transfer_count'],1);self.assertEqual(len(h.candidate()['events']),1)
        self.assertFalse(self.seed['events'])
    def test_conflict(self):
        h=History(self.seed);h.unresolved[self.trace]={**h.unresolved[self.trace],'reasons':['different']}
        with patch('repair_overlay.contexts',return_value=self.ctx):r=overlay(self.store,self.seed,h)
        self.assertEqual(r['conflicts'],1);self.assertFalse(h.candidate()['events'])
