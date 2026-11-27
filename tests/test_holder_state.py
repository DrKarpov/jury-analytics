import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from holder_state import refresh,evidence
from recovery import read
from indexer import publish
A='0:'+'1'*64
def observation():
    return {'started_at':100,'observed_at':101,'supply_raw':'10','owner_count':1,'wallet_count':1,
            'owners':[{'owner':A,'balance_raw':'10'}],'scope':'current observation'}
class HolderStateTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_match(self):
        self.assertEqual(refresh(self.p,observation)['status'],'observations_match')
        h,s=evidence(self.p,'new',now=102)
        self.assertEqual(h['candidate_digest'],'new');self.assertEqual(h['supply_raw'],'10')
    def test_preserve_on_error(self):
        refresh(self.p,observation)
        before=(self.p/'holders/latest.json').read_bytes()
        def fail():raise ValueError('different balances')
        self.assertEqual(refresh(self.p,fail)['status'],'unavailable_or_mismatch')
        self.assertEqual(before,(self.p/'holders/latest.json').read_bytes())
        h,s=evidence(self.p,'new',now=200)
        self.assertEqual(h['observed_at'],101)
        self.assertEqual(s['status'],'unavailable_or_mismatch')
    def test_reject_invalid_supply(self):
        self.assertEqual(refresh(self.p,lambda:{**observation(),'supply_raw':'11'})['status'],'unavailable_or_mismatch')
        self.assertFalse((self.p/'holders/latest.json').exists())
    def test_reject_rollback(self):
        refresh(self.p,observation)
        self.assertEqual(refresh(self.p,lambda:{**observation(),'started_at':90,'observed_at':91})['status'],'unavailable_or_mismatch')
    def test_tampered_observation(self):
        refresh(self.p,observation)
        p=self.p/'holders/latest.json';r=read(p);r['observation']['supply_raw']='12';publish(r,p)
        with self.assertRaises(ValueError):evidence(self.p,'new',now=102)
    def test_missing(self):
        h,s=evidence(self.p,'new');self.assertEqual(h['status'],'unavailable')
