import unittest,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wallet_identity import validate,addr
from indexer import TOKEN

def address_cell(w):
    wc,h=w.split(':');bits='100'+f'{int(wc)&255:08b}'+f'{int(h,16):0256b}'
    top=bits+'1'+'0'*((-len(bits)-1)%8)
    payload=int(top,2).to_bytes(len(top)//8,'big')
    cell=bytes([0,len(bits)//8+(len(bits)+7)//8])+payload
    return {'type':'cell','cell':(bytes.fromhex('b5ee9c7201010101')+bytes([len(cell),0])+cell).hex()}

def result(s):return {'success':True,'exit_code':0,'stack':s}

class IdentityTests(unittest.TestCase):
    def fixture(self):
        w='0:'+'12'*32;o='0:'+'34'*32
        code=hashlib.sha256(b'\x00\x00').hexdigest()
        wg=result([{'type':'num','num':'0'},address_cell(o),address_cell(TOKEN),{'type':'cell','cell':'b5ee9c72010101010002000000'}])
        mg=result([address_cell(w)])
        c={'jetton_wallets':[{'address':w,'owner':o,'jetton':TOKEN,'code_hash':code}]}
        return w,o,wg,mg,c
    def test_matching_getters_and_index(self):
        w,o,wg,mg,c=self.fixture()
        self.assertEqual(addr(wg['stack'][1]),o)
        self.assertEqual(validate(w,wg,mg,c)['owner'],o)
    def test_reject_wrong_master_mapping(self):
        w,o,wg,mg,c=self.fixture();mg['stack']=[address_cell(o)]
        with self.assertRaises(ValueError):validate(w,wg,mg,c)
    def test_reject_index_disagreement(self):
        w,o,wg,mg,c=self.fixture();c['jetton_wallets'][0]['owner']=w
        with self.assertRaises(ValueError):validate(w,wg,mg,c)
    def test_reject_getter_failure(self):
        w,o,wg,mg,c=self.fixture();wg['success']=False
        with self.assertRaises(ValueError):validate(w,wg,mg,c)
