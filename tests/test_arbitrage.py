import unittest
from test_indexer import H
from arbitrage import evidence_records,verify,candidate_pairs
from provider import address

class ArbitrageTests(unittest.TestCase):
    def test_real_wallet_agent_cycle(self):
        r=evidence_records()[0];w,p,q=map(address,(r['owner'],r['first'],r['second']))
        a={'trace':r['trace'],'time':r['time'],'tx':'4d31debceef3c4708cee9a9415a52350dab76bc38f139fb6935f911c1cf56fa3','lt':'119463478000049','source':p,'destination':w,'amount_raw':'26094683475','aborted':False}
        b={**a,'tx':'b3289a10e194683e2fb21a575b441fc1706c5664e859b471a26aa6a6d765a588','lt':'119463478000055','source':w,'destination':q}
        e={'kind':'sell','transfer_tx':b['tx'],'wallet':w,'quote_asset':'GRAM','quote_raw':'7209799513','time':r['time']}
        buy,c=verify(r,[a,b],[e]);self.assertEqual(buy['quote_status'],'unresolved');self.assertEqual(c['native_net_raw'],'36279491');self.assertEqual(buy['amount_raw'],b['amount_raw'])
        self.assertFalse(candidate_pairs([a,b],[e,buy]))
        broken={**r,'transactions':r['transactions'][:-1]}
        with self.assertRaises((ValueError,KeyError)):verify(broken,[a,b],[e])
