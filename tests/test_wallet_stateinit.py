import unittest,hashlib
from wallet_stateinit import boc,decode_stateinit,prefix,crc32c
from indexer import TOKEN

class StateInitTests(unittest.TestCase):
    def test_empty_cell_hash_and_crc(self):
        raw=bytes.fromhex('b5ee9c72010101010002000000')
        cells,root=boc(raw)
        self.assertEqual(cells[root]['hash'],hashlib.sha256(b'\x00\x00').digest())
        self.assertEqual(crc32c(b'123456789').hex(),'839206e3')
        crc_raw=raw[:4]+b'\x41'+raw[5:]
        self.assertEqual(boc(crc_raw+crc32c(crc_raw))[1],0)
        with self.assertRaises(ValueError):boc(crc_raw+b'\x00'*4)

    def test_stateinit_hash_from_reference_depths(self):
        raw=bytes.fromhex('b5ee9c7201010301000900020134010200000000')
        root,code,data=decode_stateinit(raw)
        empty=hashlib.sha256(b'\x00\x00').digest()
        self.assertEqual(code,empty.hex())
        self.assertEqual(root,hashlib.sha256(bytes.fromhex('02013400000000')+empty*2).hexdigest())
        self.assertEqual(data['hash'],empty)

    def test_reject_bad_root_and_exotic(self):
        for h in ('b5ee9c72010101010002000800','b5ee9c72010101010002010000','b5ee9c720101010100020000','b5ee9c7201010101000300000180'):
            with self.subTest(h=h),self.assertRaises(ValueError):boc(bytes.fromhex(h))

    def test_data_prefix_candidate(self):
        def addr(w):
            wc,h=w.split(':');return '100'+f'{int(wc)&255:08b}'+f'{int(h,16):0256b}'
        owner='0:'+'12'*32
        self.assertEqual(prefix({'bits':'0000'+addr(owner)+addr(TOKEN)+'101'}),(owner,TOKEN,'101'))
        with self.assertRaises(ValueError):prefix({'bits':'0001'+addr(owner)+addr(TOKEN)})
