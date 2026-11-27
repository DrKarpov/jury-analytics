import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from auto_repair import run,checked_attempt
from repair_overlay import RULE
from recovery import recover,read
from indexer import digest,publish
from test_repair_overlay import OverlayTests

class AutoRepairTests(unittest.TestCase):
    def setUp(self):
        self.f=OverlayTests();self.f.setUp();self.store=self.f.store
        self.r=self.f.record;self.seed=self.f.seed;self.t=self.f.trace
        (self.f.folder/(self.t+'.json')).unlink()
        self.seed['source']='Toncenter v3';self.seed['audit']='single_provider_unverified'
        self.seed['digest']=digest({k:v for k,v in self.seed.items() if k!='digest'})
        a={'trace':self.t,'status':'mismatch',**self.f.ctx[3][self.t]}
        self.a=a
        folder=self.store/'audit';folder.mkdir()
        b={'candidate_digest':self.seed['digest'],'start':0,'end':1,'rows':[a]}
        b['digest']=digest(b);publish(b,folder/'batch-00000000-00000001.json')
    def tearDown(self):self.f.tearDown()
    def center(self,e,p):return {'actions':self.r['center_actions']}
    def alternate(self,e,p):return self.r['alternate_event']
    def test_resume_without_repeat(self):
        first=run(self.store,self.center,self.alternate,seed=self.seed)
        self.assertEqual(first['installed_this_run'],1)
        self.assertEqual(first['remaining_mismatches'],0)
        def no(*a):raise AssertionError('unexpected request')
        again=run(self.store,no,no,seed=self.seed)
        self.assertEqual(again['examined_this_run'],0)
        self.assertEqual(again['active_resolutions'],1)
    def test_no_rule_checkpoint(self):
        def empty(e,p):return {'actions':[]}
        s=run(self.store,empty,self.alternate,seed=self.seed)
        self.assertEqual(s['remaining_mismatches'],1)
        self.assertEqual(s['pending_alias_checks'],0)
        q=read(self.store/'repair-queue.json');self.assertEqual(q['rows'][0]['status'],'no_rule_match')
        def no(*a):raise AssertionError('unexpected request')
        run(self.store,no,no,seed=self.seed)
    def test_transport_retry(self):
        def fail(*a):raise OSError('offline')
        s=run(self.store,self.center,fail,seed=self.seed)
        self.assertEqual(s['pending_alias_checks'],1)
        self.assertEqual(s['installed_this_run'],0)
        self.assertEqual(run(self.store,self.center,self.alternate,seed=self.seed)['installed_this_run'],1)
