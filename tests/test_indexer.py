import sys, unittest, hashlib, sqlite3, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from indexer import *
A='0:'+'1'*64; B='0:'+'2'*64; C='0:'+'3'*64
H=lambda n: hashlib.sha256(str(n).encode()).hexdigest()
def row(i,trace=1,stamp=100,aborted=False,src=B,dest=A):
    return dict(jetton_master=MASTER,transaction_aborted=aborted,amount='1000000001',transaction_lt=str(i),transaction_now=stamp,transaction_hash=H(i),trace_id=H('t'+str(trace)),source=src,destination=dest)
def swap(side='buy',trace=1,idx=1,success=True):
    ai,ao=(None,TOKEN) if side=='buy' else (TOKEN,None)
    return dict(trace_id=H('t'+str(trace)),action_id=H('a'+str(idx)),type='jetton_swap',success=success,trace_end_utime=100,details=dict(asset_in=ai,asset_out=ao,sender=A,dex='test',dex_incoming_transfer=dict(asset=ai,amount='2000000000' if ai is None else '1000000001',source=A,destination=B),dex_outgoing_transfer=dict(asset=ao,amount='2000000000' if ao is None else '1000000001',source=B,destination=A)))
def fixture(rows,acts):
    def fetch(e,p):
        if e=='jetton/transfers': result=[r for r in rows if p['start_utime']<=r['transaction_now']<=p['end_utime']];key='jetton_transfers'
        else: result=[a for a in acts if a['trace_id'] in [hash_id(i) for i in p['trace_id']]];key='actions'
        return {key:result[p['offset']:p['offset']+p['limit']]}
    return fetch
class Tests(unittest.TestCase):
    def setUp(self):self.db=open_db(':memory:')
    def tearDown(self):self.db.close()
    def test_buy(self):
        d=run(self.db,fixture([row(1)],[swap()]),cutoff=101);self.assertEqual(d['events'][0]['kind'],'buy');self.assertEqual(d['events'][0]['quote_raw'],'2000000000');self.assertEqual(d['unresolved'],[])
    def test_sell(self):
        d=run(self.db,fixture([row(1,src=A,dest=B)],[swap('sell')]),cutoff=101);self.assertEqual(d['events'][0]['kind'],'sell')
    def test_failed(self):
        d=run(self.db,fixture([row(1)],[swap(success=False)]),cutoff=101);self.assertFalse(d['events']);self.assertEqual(len(d['unresolved']),1)
    def test_abort(self):
        d=run(self.db,fixture([row(1,aborted=True)],[swap()]),cutoff=101);self.assertFalse(d['events'])
    def test_missing_action(self):
        d=run(self.db,fixture([row(1)],[]),cutoff=101);self.assertFalse(d['events']);self.assertEqual(d['unresolved'][0]['transfer_count'],1)
    def test_duplicate_action(self):
        with self.assertRaises(ValueError):run(self.db,fixture([row(1)],[swap(),swap()]),cutoff=101)
    def test_double_count(self):
        d=run(self.db,fixture([row(1)],[swap(idx=1),swap(idx=2)]),cutoff=101);self.assertFalse(d['events']);self.assertEqual(len(d['unresolved']),1)
    def test_incremental(self):
        run(self.db,fixture([row(1)],[swap()]),cutoff=101);d=run(self.db,fixture([row(1),row(2,trace=2,stamp=102)],[swap()]),cutoff=105);self.assertEqual(d['transfer_count'],2);self.assertEqual(len(d['events']),1)
    def test_changed_history(self):
        run(self.db,fixture([row(1)],[swap()]),cutoff=101)
        with self.assertRaises(ValueError):run(self.db,fixture([],[]),cutoff=102)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM transfers').fetchone()[0],1)
    def test_direct_transfer(self):
        a=swap();a['type']='jetton_transfer';a['details']=dict(asset=TOKEN,sender=B,receiver=A,amount='1000000001');d=run(self.db,fixture([row(1)],[a]),cutoff=101);self.assertEqual(d['events'][0]['kind'],'transfer')
    def test_digest(self):
        d=run(self.db,fixture([row(1)],[swap()]),cutoff=101);h=d.pop('digest');self.assertEqual(digest(d),h)
if __name__=='__main__':unittest.main()
