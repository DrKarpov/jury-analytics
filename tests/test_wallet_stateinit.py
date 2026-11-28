import unittest,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wallet_stateinit import boc,decode_stateinit,prefix,crc32c,stateinit_parts,deployment_prefix_length,deployment_address_matches,owner_prefix_matches
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

    def test_observed_provider_wrapper_normalizes_only_exact_structure(self):
        bare=bytes.fromhex('b5ee9c7201010301000900020134010200000000')
        wrapped=bytes.fromhex('b5ee9c7201010301000a000203a1a0010200000000')
        a=stateinit_parts(bare)
        b=stateinit_parts(wrapped,center=True)
        self.assertEqual(a[:3],b[:3])
        self.assertNotEqual(a[3],b[3])
        with self.assertRaises(ValueError):stateinit_parts(wrapped)
        altered=wrapped.replace(bytes.fromhex('a1a0'),bytes.fromhex('81a0'))
        with self.assertRaises(ValueError):stateinit_parts(altered,center=True)

    def test_sharded_deployment_real_saved_address(self):
        # Toncenter declared StateInit hash from mint receipt 00e872a6...
        h='c2b9d637bbbf96262ed0e55ab69eca995caa495d0c01c6dfe3f443d38d8db9fc'
        wallet='0:a5b9d637bbbf96262ed0e55ab69eca995caa495d0c01c6dfe3f443d38d8db9fc'
        owner='0:a568452b0f0298141bfdcd3d7aef32c3ccac7a03dc03016c6881777949ba4e68'
        bare=bytes.fromhex('b5ee9c7201010301000900020134010200000000')
        sharded=bytes.fromhex('b5ee9c7201010301000a000203a1a0010200000000')
        self.assertEqual(deployment_prefix_length(bare),0)
        self.assertEqual(deployment_prefix_length(sharded),8)
        self.assertTrue(deployment_address_matches(h,wallet,8))
        self.assertFalse(deployment_address_matches(h,wallet,0))
        self.assertFalse(deployment_address_matches(h,wallet[:-1]+'d',8))
        self.assertFalse(deployment_address_matches(h,'0:a5a9'+wallet[6:],8))
        self.assertTrue(owner_prefix_matches(owner,wallet,8))
        self.assertFalse(owner_prefix_matches('0:a4'+owner[4:],wallet,8))
        with self.assertRaises(ValueError):deployment_address_matches(h,wallet,9)
        with self.assertRaises(ValueError):deployment_address_matches(h,'-1:'+wallet[2:],8)
