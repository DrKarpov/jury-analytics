import unittest
from test_indexer import swap,row,fixture
from indexer import run,open_db
from venue_coverage import inventory

class VenueTests(unittest.TestCase):
    def test_no_venue_allowlist(self):
        # Synthetic standard provider action shape, not evidence of actual Moon.cx decoding.
        for label in ('moon','moon.cx','mooncx_cpmm','mooncx_clmm','future_dex'):
            a=swap();a['details']['dex']=label
            with open_db(':memory:') as db:
                data=run(db,fixture([row(1)],[a]),cutoff=101)
            self.assertEqual(data['events'][0]['venue'],label)
            self.assertEqual(inventory(data)['venue_labels'],{label:1})
    def test_unknown_action_is_unresolved(self):
        a=swap();a['type']='unverified_moon_action'
        with open_db(':memory:') as db:
            data=run(db,fixture([row(1)],[a]),cutoff=101)
        self.assertFalse(data['events'])
        r=inventory(data)
        self.assertEqual(r['classified_swaps'],0)
        self.assertEqual(r['unresolved_traces'],1)
