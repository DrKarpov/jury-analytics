import sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from indexer import digest,publish
from repair_attempt import checked_negative_attempt

class NegativeAttemptTests(unittest.TestCase):
    def test_both_persisted_schemas_and_tampering(self):
        audit={'trace':'trace','status':'mismatch'}
        for rule,version in [('exact_swap_transfer_delivery_v1',1),('dedust_v2_omniston_final_native_payout_v1',None)]:
            with self.subTest(rule=rule), tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'record.json'
                r={'rule':rule,'seed_digest':'seed','trace':'trace','audit_digest':digest(audit),'status':'no_rule_match'}
                if version is not None:r['version']=version
                r['digest']=digest(r);publish(r,path)
                checked_negative_attempt(path,'seed','trace',rule,audit)
                with self.assertRaises(ValueError):
                    checked_negative_attempt(path,'seed','different',rule,audit)
                r['version']=2;r['digest']=digest({k:v for k,v in r.items() if k!='digest'});publish(r,path)
                with self.assertRaises(ValueError):
                    checked_negative_attempt(path,'seed','trace',rule,audit)
