import sys,unittest,tempfile,subprocess
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from live_pipeline import validate_status,classify,execute,STAGES
from genesis_checkpoint import signed
from indexer import publish
MD='master'
class PipelineTests(unittest.TestCase):
    def test_reject_stale_and_wrong_dependency(self):
        base={'master_digest':MD,'target_timestamp':12,'frontier_digest':'a'}
        with self.assertRaisesRegex(ValueError,'target is stale'):
            validate_status('counterparts',signed(base),13,MD,{})
        with self.assertRaisesRegex(ValueError,'frontier mismatch'):
            validate_status('counterparts',signed(base),12,MD,{'accounts':{'frontier_digest':'b'}})
        self.assertEqual(validate_status('counterparts',signed(base),12,MD,{'accounts':{'frontier_digest':'a'}})['target_timestamp'],12)
    def test_backlog_is_not_silently_successful_or_a_crash(self):
        self.assertEqual(classify('master',{'target_reached':False,'pending_receipts':3},('pending_receipts',)),{'pending_receipts':3,'target_reached':False})
        self.assertEqual(classify('accounts',{'pending_failure_accounts':0},('pending_failure_accounts',)),{})
    def test_failure_stops_dependents_and_keeps_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=root/'store';(store/'genesis'/'v1').mkdir(parents=True);(store/'continuation'/'v1').mkdir(parents=True)
            publish({'cutoff':12},store/'update-status.json')
            publish(signed({'test':True}),store/'genesis'/'v1'/'master.json')
            calls=[]
            def runner(args,**kw):
                calls.append(args)
                raise subprocess.CalledProcessError(1,args)
            with patch('live_pipeline.git',return_value='head'):
                with self.assertRaisesRegex(RuntimeError,'downstream stages not executed'):
                    execute(store,root/'report.json',runner)
            import json
            result=json.loads((root/'report.json').read_text())
            self.assertEqual(len(calls),1)
            self.assertEqual(result['failed_stage'],'accounts')
            self.assertEqual(result['outcome'],'failed')
            self.assertFalse(result['all_stages_checkpointed'])
            self.assertFalse((store/'continuation'/'v1'/'pipeline-status.json').exists())
