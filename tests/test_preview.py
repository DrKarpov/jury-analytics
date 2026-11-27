import sys, unittest, copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from indexer import digest, MASTER
from preview import assemble
A='0:'+'1'*64
class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.c={'schema':2,'token':MASTER,'cutoff':123,'events':[],'unresolved':[],'transfers':[],'transfer_count':0};self.c['digest']=digest(self.c);h=self.c['digest'];self.a={'snapshot_digest':h,'status':'partial'};self.h={'candidate_digest':h,'owners':[{'owner':A,'balance_raw':'12'}],'supply_raw':'12','owner_count':1,'wallet_count':1,'observed_at':125};self.l={'candidate_digest':h,'events':[]};self.s={'candidate_digest':h,'cutoff':123,'mints':[],'burns':[]}
    def run_bundle(self):return assemble(self.c,self.a,self.h,self.l,self.s)
    def test_bundle(self):self.assertEqual(self.run_bundle()['evidence']['mode'],'staging');self.assertEqual(self.run_bundle()['evidence']['holders']['supply_raw'],'12')
    def test_evidence_digest(self):
        evidence=self.run_bundle()['evidence'];self.assertEqual(evidence['digest'],digest({k:v for k,v in evidence.items() if k!='digest'}))
    def test_modified_candidate(self):
        self.c['cutoff']=124
        with self.assertRaises(ValueError):self.run_bundle()
    def test_wrong_audit(self):
        self.a['snapshot_digest']='other'
        with self.assertRaises(ValueError):self.run_bundle()
    def test_mixed_evidence(self):
        self.h['candidate_digest']='other'
        with self.assertRaises(ValueError):self.run_bundle()
    def test_inconsistent_supply(self):
        self.h['supply_raw']='13'
        with self.assertRaises(ValueError):self.run_bundle()
    def test_duplicate_owner(self):
        self.h['owners']*=2;self.h['owner_count']=2;self.h['supply_raw']='24'
        with self.assertRaises(ValueError):self.run_bundle()
    def test_cutoff(self):
        self.s['cutoff']=124
        with self.assertRaises(ValueError):self.run_bundle()
    def test_holder_unavailable(self):
        self.h={'candidate_digest':self.c['digest'],'status':'unavailable'}
        self.assertIsNone(self.run_bundle()['evidence']['holders'])
