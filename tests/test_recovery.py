import sys, tempfile, unittest, json
from pathlib import Path
from urllib.error import URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from recovery import recover,load_seed,audit_batch,load_progress
from indexer import digest,MASTER,publish

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.src=self.root/'src';self.src.mkdir();self.store=self.root/'store';self.store.mkdir()
        self.ids=['1'*64,'2'*64,'3'*64]
        self.c={'token':MASTER,'schema':2,'cutoff':100,'trace_count':3,'transfer_count':3,'transfers':[{'trace':t,'tx':t} for t in self.ids],'events':[],'unresolved':[{'trace':t} for t in self.ids]}
        self.c['digest']=digest(self.c);self.h=self.c['digest'];publish(self.c,self.src/'candidate.json')
        for k in ('liquidity','lifecycle'):publish({'candidate_digest':self.h},self.src/(k+'.json'))
        recover(self.src,self.store,self.h)
    def tearDown(self): self.tmp.cleanup()
    def fetch(self,endpoint,params):
        return {'event_id':endpoint.split('/')[-1],'in_progress':False,'actions':[]}
    def test_seed_roundtrip(self):
        self.assertEqual(load_seed(self.store,self.h),self.c)
        recover(self.src,self.store,self.h)
    def test_resume(self):
        r=audit_batch(self.store,self.c,self.fetch,limit=2)
        self.assertEqual(r['attempted'],2);self.assertEqual(r['status'],'partial')
        calls=[]
        def fetch(e,p):calls.append(e);return self.fetch(e,p)
        r=audit_batch(self.store,self.c,fetch,limit=2)
        self.assertEqual(calls,['events/'+self.ids[2]])
        self.assertEqual(r['status'],'discovered_trace_swaps_match')
        audit_batch(self.store,self.c,fetch,limit=2);self.assertEqual(len(calls),1)
    def test_transport_preserves_cursor(self):
        def fetch(e,p):
            if e.endswith(self.ids[1]):raise URLError('test')
            return self.fetch(e,p)
        self.assertEqual(audit_batch(self.store,self.c,fetch,limit=3)['attempted'],1)
        self.assertEqual(audit_batch(self.store,self.c,self.fetch,limit=3)['attempted'],3)
    def test_bad_segment(self):
        publish([],self.store/'seed'/'transfers'/'000000.json')
        with self.assertRaises(ValueError):load_seed(self.store,self.h)
    def test_bad_checkpoint(self):
        audit_batch(self.store,self.c,self.fetch,limit=2)
        p=next((self.store/'audit').glob('batch-*.json'));b=json.loads(p.read_text());b['rows'][0]['status']='mismatch';publish(b,p)
        with self.assertRaises(ValueError):load_progress(self.store,self.c)
    def test_unavailable_not_verified(self):
        r=audit_batch(self.store,self.c,lambda e,p:{},limit=3)
        self.assertEqual(r['unavailable'],3);self.assertEqual(r['status'],'review_required')
