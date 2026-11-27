import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from persistent_preview import bundle
from recovery import recover,audit_batch
from incremental import advance
from indexer import digest,publish
from test_incremental import seed
from test_indexer import fixture,row,swap

class PersistentPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.store=root/'store';self.store.mkdir();src=root/'src';src.mkdir()
        self.seed=seed();self.h=self.seed['digest'];publish(self.seed,src/'candidate.json')
        for k in ('liquidity','lifecycle'):publish({'candidate_digest':self.h},src/(k+'.json'))
        recover(src,self.store,self.h)
    def tearDown(self):self.tmp.cleanup()
    def build(self):
        from recovery import load_seed
        with patch('persistent_preview.load_seed',lambda s:load_seed(s,self.h)):
            return bundle(self.store)
    def test_seed_scope_and_evidence(self):
        b=self.build();e=b['evidence']
        self.assertEqual(e['mode'],'staging')
        self.assertEqual(e['swap_audit']['checked'],0)
        self.assertEqual(e['seed_audit']['candidate_digest'],self.h)
        self.assertEqual(e['digest'],digest({k:v for k,v in e.items() if k!='digest'}))
        self.assertIsNone(e['holders'])
    def test_new_snapshot_does_not_inherit_old_audit(self):
        audit_batch(self.store,self.seed,lambda e,p:{'event_id':e.split('/')[-1],'in_progress':False,'actions':[]},limit=1)
        advance(self.store,fixture([row(1),row(2,trace=2,stamp=102)],[swap()]),105,self.seed)
        b=self.build();e=b['evidence']
        self.assertEqual(b['transfer_count'],2)
        self.assertNotEqual(b['digest'],self.h)
        self.assertEqual(e['seed_audit']['attempted'],1)
        self.assertEqual(e['swap_audit']['checked'],0)
        self.assertEqual(e['swap_audit']['snapshot_digest'],b['digest'])
        self.assertEqual(e['lifecycle']['status'],'not_checked_for_current_candidate')
        self.assertNotIn('events',e['liquidity'])
