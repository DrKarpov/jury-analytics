import sys,unittest,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from provider import paired

class PairedTests(unittest.TestCase):
    def test_overlaps_two_independent_calls_and_keeps_order(self):
        barrier=threading.Barrier(2,timeout=2)
        def fetch(x):
            barrier.wait()
            return x
        self.assertEqual(paired(lambda:fetch('primary'),lambda:fetch('alternate')),('primary','alternate'))
    def test_transport_failure_does_not_return_partial_proof(self):
        def fail():raise TimeoutError('simulated provider failure')
        with self.assertRaises(TimeoutError):paired(fail,lambda:1)
