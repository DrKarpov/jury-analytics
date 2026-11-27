import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from discrepancy import category,transfer_support,multiset,tree_index
A='0:'+'1'*64; B='0:'+'2'*64; T='a'*64; U='b'*64
def swap(q=10,quote=20,side='buy'):return [[side,A,q,'GRAM',quote],1]
class DiscrepancyTests(unittest.TestCase):
    def test_categories(self):
        x=swap();y=swap(q=11)
        for p,a,want in [([],[x],'primary_missing'),([x],[],'alternate_missing'),
                         ([x],[x,y],'alternate_extra'),([x,y],[x],'primary_extra'),
                         ([x],[swap(quote=21)],'quote_difference'),([x],[y],'endpoint_or_other_difference')]:
            self.assertEqual(category({'primary_swaps':p,'alternate_swaps':a}),want)
    def test_transfer_support_is_not_quote_proof(self):
        r={'tx':T,'amount_raw':'10','source':B,'destination':A,'aborted':False}
        s=transfer_support(multiset([swap(quote=900)]),[r])
        self.assertTrue(s[0]['unique_candidate']);self.assertEqual(s[0]['swap'][-1],'900')
        self.assertFalse(transfer_support(multiset([swap()]),[r,{**r,'tx':U}])[0]['unique_candidate'])
        self.assertFalse(transfer_support(multiset([swap()]),[{**r,'aborted':True}])[0]['unique_candidate'])
    def test_raw_tree_identity(self):
        tree={'transaction':{'hash':T},'children':[{'transaction':{'hash':U}}]}
        self.assertEqual(set(tree_index(tree,T)),{T,U})
        with self.assertRaises(ValueError):tree_index(tree,U)
        with self.assertRaises(ValueError):tree_index({**tree,'emulated':True},T)
        with self.assertRaises(ValueError):tree_index({'transaction':{'hash':T},'children':[{'transaction':{'hash':T}}]},T)
