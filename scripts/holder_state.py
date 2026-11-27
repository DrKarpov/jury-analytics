"""Persist independent current holder observations, never overwrite a good observation on failure."""
import argparse, time, urllib.error
from pathlib import Path
from audit import holder_snapshot
from indexer import MASTER, digest, publish, integer
from provider import address
from recovery import read

def validate(record):
    if record.get('version')!=1 or record.get('token')!=MASTER:
        raise ValueError('wrong holder observation identity')
    if digest({k:v for k,v in record.items() if k!='digest'})!=record.get('digest'):
        raise ValueError('holder observation checksum mismatch')
    h=record['observation']
    if not 0<h['started_at']<=h['observed_at']:
        raise ValueError('holder observation time mismatch')
    owners=h['owners']; seen=set(); total=0
    for r in owners:
        a=address(r['owner']);b=integer(r['balance_raw'])
        if a!=r['owner'] or a in seen or b<=0:raise ValueError('invalid holder owner')
        seen.add(a);total+=b
    if total!=integer(h['supply_raw']) or len(owners)!=h['owner_count'] or h['wallet_count']<len(owners):
        raise ValueError('holder supply/count mismatch')
    return record

def refresh(store, observe=holder_snapshot):
    folder=store/'holders';folder.mkdir(exist_ok=True)
    latest=folder/'latest.json';status=folder/'status.json'
    prior=validate(read(latest)) if latest.exists() else None
    attempted=int(time.time())
    try:
        h=observe()
        record={'version':1,'token':MASTER,'observation':h}
        record['digest']=digest(record);validate(record)
        if prior and h['observed_at']<prior['observation']['observed_at']:
            raise ValueError('holder observation rollback')
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as e:
        reason='http_'+str(e.code) if isinstance(e,urllib.error.HTTPError) else type(e).__name__
        report={'status':'unavailable_or_mismatch','attempted_at':attempted,'reason':reason,
                'last_valid_digest':prior['digest'] if prior else None}
    else:
        publish(record,latest)
        report={'status':'observations_match','attempted_at':attempted,'last_valid_digest':record['digest']}
    publish(report,status)
    print(report,flush=True)
    return report

def evidence(store,candidate_digest,now=None):
    folder=store/'holders';latest=folder/'latest.json';status=folder/'status.json'
    now=int(time.time()) if now is None else now
    report=read(status) if status.exists() else {'status':'not_checked'}
    if not latest.exists():
        if report.get('last_valid_digest'):raise ValueError('missing last valid holders')
        return {'candidate_digest':candidate_digest,'status':'unavailable'},report
    record=validate(read(latest));h=record['observation']
    if report.get('last_valid_digest')!=record['digest']:
        raise ValueError('holder status/evidence mismatch')
    if h['observed_at']>now:raise ValueError('future holder observation')
    # Current independently observed holders, not a balance as of the transfer cutoff.
    return {**h,'candidate_digest':candidate_digest,'observation_digest':record['digest']},report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);a=p.parse_args();refresh(a.store)
