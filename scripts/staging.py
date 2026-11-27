"""Collect candidate privately, run independent checks, retain evidence. No publication."""
import argparse, json, sys
from pathlib import Path
from indexer import open_db, run, publish, digest, ROOT
from audit import compare, holder_snapshot
from lifecycle import collect, liquidity
from provider import request


def main():
    p=argparse.ArgumentParser(); p.add_argument('--db',type=Path,default=ROOT/'data/index.sqlite');p.add_argument('--dir',type=Path,default=ROOT/'data/staging');p.add_argument('--full',action='store_true');p.add_argument('--max-traces',type=int);a=p.parse_args()
    if a.max_traces is not None and a.max_traces<=0: p.error('positive audit limit required')
    a.dir.mkdir(parents=True,exist_ok=True);a.db.parent.mkdir(parents=True,exist_ok=True)
    for name in ("candidate.json","swap-audit.json","holders.json","lifecycle.json","liquidity.json"):
        (a.dir/name).unlink(missing_ok=True)
    with open_db(a.db) as db:
        snapshot=run(db,full=a.full)
        publish({**liquidity(db,snapshot["cutoff"]),"candidate_digest":snapshot["digest"]},a.dir/"liquidity.json")
    publish(snapshot,a.dir/'candidate.json')
    try:
        supply=collect(request,snapshot["cutoff"]);publish({**supply,"candidate_digest":snapshot["digest"]},a.dir/"lifecycle.json");supply_status="collected_unverified"
    except Exception as e:
        supply_status="unavailable";publish({"status":supply_status,"error":type(e).__name__,"candidate_digest":snapshot["digest"]},a.dir/"lifecycle.json")
    audit=compare(snapshot,max_traces=a.max_traces);publish(audit,a.dir/'swap-audit.json')
    try:
        holders=holder_snapshot();publish({**holders,'candidate_digest':snapshot['digest']},a.dir/'holders.json');holder_status='observations_match'
    except Exception as e:
        holder_status='unavailable_or_mismatch';publish({'status':holder_status,'error':type(e).__name__,'candidate_digest':snapshot['digest']},a.dir/'holders.json')
    print(json.dumps({'swap_audit':audit['status'],'holders':holder_status,'supply':supply_status,'candidate':str(a.dir/'candidate.json')}))
    # Even a matched comparison is not proof of global history completeness. Never auto-publish.
    return 0 if audit['status']=='discovered_trace_swaps_match' and holder_status=='observations_match' and supply_status=='collected_unverified' else 2
if __name__=='__main__':sys.exit(main())
