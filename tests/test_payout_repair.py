"""Regression check against the original independently collected raw trace archive."""
import sys,json,unittest,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from payout_repair import propose
from discrepancy import multiset

class PayoutTests(unittest.TestCase):
    def test_real_cases(self):
        root=os.environ.get('JURY_DISCREPANCY_FIXTURES')
        if not root:self.skipTest('live regression archive supplied by workflow')
        files=list(Path(root).glob('*.json'))
        checked=0
        for f in files:
            if f.name=='report.json':continue
            d=json.loads(f.read_text());a=d['audit_row']
            if d['diagnostic']['category']!='quote_difference':continue
            # Use the original seed cutoff (all diagnostic transactions are older).
            from indexer import classify
            cutoff=1795783350;t=a['trace']
            old=d['seed_events'];_,u=classify(t,d['center_actions'],d['transfers'],cutoff,allow_alias=False)
            p=propose(t,d['center_actions'],d['transfers'],old,u,cutoff,multiset(a['alternate_swaps']),d['raw_trace'])
            self.assertIsNotNone(p,t);checked+=1
            self.assertGreater(p['changed_quotes'],0)
            # Alter the root hash; the same proposal must be rejected.
            tree=d['raw_trace'];tree['transaction']['hash']='0'*64
            self.assertIsNone(propose(t,d['center_actions'],d['transfers'],old,u,cutoff,multiset(a['alternate_swaps']),tree))
        self.assertEqual(checked,2)
