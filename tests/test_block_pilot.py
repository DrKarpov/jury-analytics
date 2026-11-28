import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from block_pilot import enumerate_pages,inspect_block
W='0:'+'a'*64
def tx(i,alt=False):
    return {'hash':f'{i:064x}','account':{'address':W} if alt else W,'lt':str(i),
            'utime' if alt else 'now':100,'mc_block_seqno':10,'in_msg':None,'out_msgs':[]}
class BlockPilotTests(unittest.TestCase):
    def test_terminal_page_and_duplicates(self):
        pages=[]
        def fetch(ep,p):return {'transactions':[tx(1),tx(2)] if p['offset']==0 else [tx(3)]}
        rows,complete=enumerate_pages(fetch,10,False,pages,size=2,max_pages=3)
        self.assertTrue(complete);self.assertEqual(len(rows),3);self.assertEqual(len(pages),2)
        with self.assertRaisesRegex(ValueError,'duplicate block'):
            enumerate_pages(lambda e,p:{'transactions':[tx(1),tx(2)]},10,False,[],size=2,max_pages=3)
    def test_budget_not_complete(self):
        rows,complete=enumerate_pages(lambda e,p:{'transactions':[tx(1)]},10,False,[],size=1,max_pages=1)
        self.assertFalse(complete)
    def test_agreement_requires_same_census_and_terminal_pages(self):
        c={tx(1)['hash']:tx(1)};a={tx(1)['hash']:tx(1,True)}
        self.assertTrue(inspect_block(10,c,a,True,True,{},set())['enumerations_agree'])
        self.assertFalse(inspect_block(10,c,a,True,False,{},set())['enumerations_agree'])
        self.assertFalse(inspect_block(10,c,{},True,True,{},set())['enumerations_agree'])
        self.assertFalse(inspect_block(10,c,{tx(1)['hash']:{**tx(1,True),'lt':'2'}},True,True,{},set())['enumerations_agree'])
