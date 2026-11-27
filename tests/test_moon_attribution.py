import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from types import SimpleNamespace
from moon_attribution import registry,scan,referral_fields

class MoonAttributionTests(unittest.TestCase):
    def test_registry(self):
        h,a=registry()
        self.assertIn('MoonPoolLegacy',h.values())
        self.assertIn('MoonClmmRange',h.values())
        self.assertTrue(all(len(k)==64 for k in h))
    def test_evidence_scope(self):
        a='0:'+'1'*64;b='0:'+'2'*64
        h=SimpleNamespace(traces={'t':[{'source':a,'destination':b}]})
        self.assertEqual(scan(h,{a:'MoonOrderNew'},{b:'MoonPool'})['t'],{(a,'MoonOrderNew','catalog_address'),(b,'MoonPool','current_code_hash')})
    def test_explicit_referral(self):
        a='0:'+'1'*64
        self.assertEqual(list(referral_fields({'payload':{'referral_address':a,'recipient':a}})),[('payload.referral_address',a)])
