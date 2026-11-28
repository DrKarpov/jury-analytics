import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from canonical_movements import Observations
from unified_shadow import add_peers,assert_preserved,frontier
from genesis_checkpoint import ANCHOR
A='0:'+'a'*64
B='0:'+'b'*64
M={'hash':'11'*32,'source':A,'destination':B,'amount_raw':'10','bounced':False,'token_opcode':'0x178d4519'}
S={'tx':'22'*32,'lt':10,'time':ANCHOR+1,'aborted':False,'alternate_success':True,'in':None,'out':[M]}
R={'tx':'33'*32,'lt':11,'time':ANCHOR+2,'aborted':False,'alternate_success':True,'in':M,'out':[]}
class UnifiedTests(unittest.TestCase):
    def test_peer_prefix_closes_frontier_and_duplicates_do_not_double_count(self):
        o=Observations();o.ingest([(A,S)])
        before=o.project({A})
        self.assertEqual(len(frontier(o,{A})),1)
        inc,conf=add_peers(o,{B:{'rows':[R]}},{B:{'new_rows':[R]}})
        self.assertEqual((inc,conf),([B],{}))
        after=o.project({A});assert_preserved(before,after)
        self.assertEqual(after['matched_deliveries'],1)
        self.assertEqual(frontier(o,{A}),[])
    def test_conflicting_prefix_excluded_as_unit(self):
        o=Observations();o.ingest([(A,S),(B,R)])
        before=o.project({A})
        inc,conf=add_peers(o,{B:{'rows':[{**R,'lt':12}]}},{})
        self.assertEqual(inc,[]);self.assertIn(B,conf)
        self.assertEqual(o.project({A}),before)
    def test_cannot_remove_existing_movement(self):
        o=Observations();o.ingest([(A,S),(B,R)])
        with self.assertRaisesRegex(ValueError,'changed existing movement'):
            assert_preserved(o.project({A}),{'events':[]})
