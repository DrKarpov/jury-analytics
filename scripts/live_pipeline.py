"""Dependency-ordered shadow acquisition, checkpointing and timing.

A process failure stops downstream stages; expected bounded coverage gaps
remain explicit. This is orchestration, not a new classifier or ledger.
"""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
from genesis_checkpoint import checked,signed
from indexer import integer,publish
from recovery import read

HERE=Path(__file__).resolve().parent
# Each stage has a bounded provider budget and an independent wall timeout.
STAGES=(
    ('accounts','continuation_store.py',('--limit','12','--seconds','90'),125,
     'status.json',('accounts','status.json','frontier.json','pending.json'),('pending_failure_accounts',)),
    ('counterparts','counterpart_discovery.py',('--limit','20','--seconds','80'),110,
     'counterpart-status.json',('counterparts','counterpart-status.json','counterpart-pending.json'),('pending_failure_edges',)),
    ('peer_prefixes','peer_prefix.py',('--limit','8','--seconds','55'),80,
     'peer-status.json',('peer-prefixes','peer-status.json','peer-pending.json'),('pending_failure_peers',)),
    ('master','master_continuation.py',('--seconds','55'),80,
     'master/status.json',('master',),('pending_receipts',)),
    ('unified','unified_shadow.py',('--limit','6','--seconds','40'),65,
     'unified-status.json',('peer-accounts','unified-status.json','unified-frontier.json','unified-pending.json'),('peer_pending_failures','master_roots_without_rows')),
)

def require(ok,message):
    if not ok:raise ValueError(message)

def git(store,*args):
    return subprocess.check_output(['git','-C',str(store),*args],text=True,timeout=20).strip()

def validate_status(name,status,target,master_digest,completed):
    checked(status)
    require(status['master_digest']==master_digest,'stage master identity mismatch')
    if name!='peer_prefixes':
        require(integer(status['target_timestamp'])==target,'stage target is stale')
    if name=='counterparts':
        require(status['frontier_digest']==completed['accounts']['frontier_digest'],'counterpart frontier mismatch')
    if name=='peer_prefixes':
        require(status['counterpart_records']==completed['counterparts']['persisted_records'],'peer evidence census mismatch')
    if name=='unified':
        require(status['historical_and_regular_matched_deliveries']==completed['accounts']['combined_matched_deliveries'],'unified account count mismatch')
        require(status['master_target_reached']==completed['master']['target_reached'],'unified master target mismatch')
    if name!='counterparts':
        require(status.get('cold_replay_equal') is True,'stage replay not confirmed')
    return status

def classify(name,status,failures):
    reasons={k:status[k] for k in failures if status.get(k)}
    if status.get('stop_reason'):reasons['stop_reason']=status['stop_reason']
    if status.get('capture_failure'):reasons['capture_failure']=status['capture_failure']
    if name=='master' and not status['target_reached']:reasons['target_reached']=False
    if name=='unified' and status.get('peer_projection_conflicts'):reasons['peer_projection_conflicts']=status['peer_projection_conflicts']
    return reasons

def execute(store,report,runner=subprocess.run):
    store=store.resolve();report=report.resolve();report.parent.mkdir(parents=True,exist_ok=True)
    target=integer(read(store/'update-status.json')['cutoff'])
    master=checked(read(store/'genesis'/'v1'/'master.json'));md=master['digest']
    source=git(HERE.parent,'rev-parse','HEAD');base=git(store,'rev-parse','HEAD')
    folder=store/'continuation'/'v1'
    started=time.monotonic()
    entries=[];completed={};fatal=None
    def report_now():
        status={'version':1,'source_sha':source,'data_start_sha':base,'target_timestamp':target,'master_digest':md,
                'run_id':os.environ.get('GITHUB_RUN_ID'),'event':os.environ.get('EVENT_NAME'),
                'elapsed_seconds':round(time.monotonic()-started,3),'stages':entries,
                'failed_stage':fatal,'all_stages_checkpointed':len(completed)==len(STAGES) and fatal is None,
                'scope':'operational stage execution and integrity checks; not proof of complete coverage or production readiness'}
        status['degraded_stages']=[x['stage'] for x in entries if x['outcome']=='checkpointed_degraded']
        status['outcome']='failed' if fatal else 'running' if len(completed)!=len(STAGES) else 'degraded' if status['degraded_stages'] else 'checkpointed'
        publish(signed(status),report)
        return status
    report_now()
    for name,script,args,timeout,status_path,paths,failures in STAGES:
        stage_start=time.monotonic()
        before=git(store,'rev-parse','HEAD')
        item={'stage':name,'data_before':before,'outcome':'running'}
        entries.append(item);report_now()
        try:
            runner([sys.executable,'-u',str(HERE/script),'--store',str(store),*args],check=True,timeout=timeout)
            status=validate_status(name,read(folder/status_path),target,md,completed)
            reasons=classify(name,status,failures)
            runner(['bash',str(HERE/'checkpoint.sh'),str(store),'Checkpoint shadow pipeline: '+name,
                    *['continuation/v1/'+x for x in paths]],check=True,timeout=35)
            item.update(outcome='checkpointed_degraded' if reasons else 'checkpointed',
                        data_after=git(store,'rev-parse','HEAD'),status_digest=status['digest'],degraded_reasons=reasons)
            completed[name]=status
        except (subprocess.SubprocessError,OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            fatal=name
            item.update(outcome='failed',error_type=type(exc).__name__,error=str(exc)[:240])
        item['elapsed_seconds']=round(time.monotonic()-stage_start,3)
        print('LIVE STAGE',json.dumps(item,sort_keys=True),flush=True)
        report_now()
        if fatal:break
    result=report_now()
    print('LIVE PIPELINE',json.dumps(result,sort_keys=True),flush=True)
    if fatal:raise RuntimeError('shadow stage failed; downstream stages not executed: '+fatal)
    # Publish only a fully executed dependency chain's operational report.
    # On failure, the artifact retains the error while earlier commits survive.
    publish(signed(result),folder/'pipeline-status.json')
    runner(['bash',str(HERE/'checkpoint.sh'),str(store),'Checkpoint shadow pipeline operational status',
            'continuation/v1/pipeline-status.json'],check=True,timeout=35)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args();execute(a.store,a.report)
