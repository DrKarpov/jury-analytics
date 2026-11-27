import unittest
from test_indexer import row,swap,A,B,H
from indexer import classify, TOKEN, normalized, endpoint_asset
from repair_alias import propose, swaps

class AliasTests(unittest.TestCase):
    def scenario(self,side):
        a=swap(side);d=a['details'];d['dex']='dedust'
        key='dex_outgoing_transfer' if side=='buy' else 'dex_incoming_transfer'
        d[key]['asset']='255:'+TOKEN.split(':',1)[1].upper()
        r=normalized(row(1,src=B if side=='buy' else A,dest=A if side=='buy' else B))
        return a,[r]
    def test_both_sides(self):
        for side in ('buy','sell'):
            a,r=self.scenario(side);t=H('t1')
            old,u=classify(t,[a],r,101,allow_alias=False)
            self.assertFalse(old);self.assertIn('unverified_swap',u['reasons'])
            new,v=classify(t,[a],r,101)
            self.assertEqual(len(new),1);self.assertEqual(new[0]['kind'],side);self.assertIsNone(v)
            self.assertEqual(propose(t,[a],r,old,u,101,swaps(new))['added'],1)
    def test_no_general_address_alias(self):
        other='-1:'+'a'*64
        self.assertNotEqual(endpoint_asset('255:'+'a'*64,other,'dedust'),other)
        self.assertNotEqual(endpoint_asset('255:'+TOKEN.split(':')[1],TOKEN,'stonfi_v2'),TOKEN)
        self.assertNotEqual(endpoint_asset('255:'+TOKEN.split(':')[1],'GRAM','dedust'),'GRAM')
    def test_failed_and_aborted(self):
        a,r=self.scenario('buy');a['success']=False
        self.assertFalse(classify(H('t1'),[a],r,101)[0])
        a['success']=True;r[0]['aborted']=True
        self.assertFalse(classify(H('t1'),[a],r,101)[0])
    def test_no_repair_if_alternate_disagrees(self):
        a,r=self.scenario('buy');t=H('t1')
        old,u=classify(t,[a],r,101,allow_alias=False)
        self.assertIsNone(propose(t,[a],r,old,u,101,swaps([])))
    def test_no_repair_if_baseline_changed(self):
        a,r=self.scenario('buy');t=H('t1')
        new,v=classify(t,[a],r,101)
        self.assertIsNone(propose(t,[a],r,new,v,101,swaps(new)))
