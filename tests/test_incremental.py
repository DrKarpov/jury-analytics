import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from incremental import History, build_update, advance, load_history
from indexer import digest, MASTER
from test_indexer import row, fixture, swap, H

def seed():
    from indexer import run, open_db
    with open_db(':memory:') as db:return run(db,fixture([row(1)],[swap()]),cutoff=101)

class IncrementalTests(unittest.TestCase):
    def test_append_and_resume(self):
        c=seed()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            r=advance(p,fixture([row(1),row(2,trace=2,stamp=102)],[swap()]),105,c)
            self.assertEqual((r['transfer_count'],r['new_transfers']),(2,1))
            h=load_history(p,c);self.assertEqual(h.cutoff,105)
            r=advance(p,fixture([row(1),row(2,trace=2,stamp=102),row(3,trace=3,stamp=106)],[swap()]),110,c)
            self.assertEqual((r['transfer_count'],r['new_transfers']),(3,1))
            self.assertEqual(len(list((p/'updates').glob('batch-*.json'))),2)
    def test_no_old_network_range(self):
        c=seed();c['cutoff']=10000;c['digest']=digest({k:v for k,v in c.items() if k!='digest'})
        calls=[]
        def f(e,p):
            calls.append((e,p));return {'jetton_transfers':[]}
        b=build_update(History(c),f,10100)
        self.assertEqual(calls[0][1]['start_utime'],6400)
        self.assertEqual(b['to_cutoff'],10100)
    def test_changed_history_rejected(self):
        h=History(seed())
        with self.assertRaisesRegex(ValueError,'overlap'):build_update(h,fixture([],[]),105)
        self.assertEqual(h.cutoff,101)
    def test_late_arrival_explicit(self):
        h=History(seed())
        b=build_update(h,fixture([row(1),row(2,trace=2,stamp=100)],[swap()]),105)
        self.assertEqual(b['late_transfers'],1);h.apply(b)
        self.assertEqual(h.candidate()['transfer_count'],2)
    def test_tampered_batch(self):
        h=History(seed());b=build_update(h,fixture([row(1)],[swap()]),105)
        b['to_cutoff']=106
        with self.assertRaisesRegex(ValueError,'digest'):h.apply(b)
    def test_cross_boundary_trace(self):
        h=History(seed());b=build_update(h,fixture([row(1),row(2,trace=1,stamp=102)],[swap()]),105)
        self.assertEqual(len(b['patches']),1);h.apply(b)
        self.assertEqual(h.candidate()['transfer_count'],2)
        self.assertEqual(h.candidate()['trace_count'],1)
    def test_cutoff_bounded(self):
        h=History(seed());b=build_update(h,fixture([row(1)],[swap()]),100000)
        self.assertEqual(b['to_cutoff'],3701)
    def test_transport_failure_no_checkpoint(self):
        c=seed()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            def f(e,p):raise OSError('offline')
            with self.assertRaises(OSError):advance(p,f,105,c)
            self.assertEqual(load_history(p,c).cutoff,101)
            self.assertFalse((p/'updates').exists())
