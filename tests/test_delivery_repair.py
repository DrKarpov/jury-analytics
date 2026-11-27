import sys,unittest,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from delivery_repair import match_delivery,propose
from recovery import load_seed,read
from repair_overlay import contexts
from discrepancy import multiset

class DeliveryTests(unittest.TestCase):
    def test_does_not_guess_ambiguous(self):
        a={'details':{'dex':'unknown'}}
        self.assertEqual(match_delivery(a,{},[{},{}],1,{}),[])
    def test_real_saved_cases(self):
        path=os.environ.get('JURY_HISTORY_FIXTURES')
        if not path:self.skipTest('saved data branch supplied in integration workflow')
        store=Path(path);seed=load_seed(store);rows,events,unresolved,audit=contexts(store,seed)
        for prefix in ('00cd4f','016b67'):
            t=next(t for t in audit if t.startswith(prefix))
            raw=next((store/'triage-raw'/'v1').glob(t+'-*.json'))
            tree=read(raw)['tree'];acts=read(store/'triage'/'v1'/raw.name)['actions']
            p=propose(t,acts,rows[t],events[t],unresolved.get(t),seed['cutoff'],multiset(audit[t]['alternate_swaps']),tree)
            self.assertIsNotNone(p,t);self.assertEqual(p['added'],1)
            self.assertIsNotNone(p['unresolved'])
            tree['transaction']['hash']='0'*64
            self.assertIsNone(propose(t,acts,rows[t],events[t],unresolved.get(t),seed['cutoff'],multiset(audit[t]['alternate_swaps']),tree))
