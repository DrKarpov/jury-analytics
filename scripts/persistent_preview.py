"""Build an unpublished preview from a pinned, validated persistent data checkout."""
import argparse, shutil
from pathlib import Path
from indexer import ROOT, digest, publish
from recovery import load_seed, load_progress, read
from incremental import load_history
from preview import assemble
from holder_state import evidence as holder_evidence
from repair_overlay import overlay
from payout_repair import overlay as payout_overlay
from delivery_repair import overlay as delivery_overlay

def bundle(store):
    seed=load_seed(store)
    h=load_history(store,seed)
    repairs=overlay(store,seed,h)
    payouts,_=payout_overlay(store,seed,h)
    deliveries,_=delivery_overlay(store,seed,h)
    c=h.candidate()
    ids,cursor,counts=load_progress(store,seed)
    # Seed audit has its own identity; it must never be presented as an audit of the new candidate.
    seed_audit={'candidate_digest':seed['digest'],'cutoff':seed['cutoff'],
                'total_traces':len(ids),'attempted':cursor,'matched':counts['match'],
                'mismatch':counts['mismatch'],'unavailable':counts['unavailable']}
    seed_audit['status']='partial' if cursor<len(ids) else 'review_required' if counts['mismatch'] or counts['unavailable'] else 'discovered_trace_swaps_match'
    d=c['digest']
    a={'snapshot_digest':d,'status':'partial','scope':'current candidate not independently audited; seed results reported separately',
       'checked':0,'matched':0,'differences':[],'unavailable':[]}
    # Reuse seed diagnostics only if candidate identity is identical. No extrapolation to new cutoff.
    unavailable={'candidate_digest':d,'status':'not_checked_for_current_candidate'}
    liquidity=read(store/'seed'/'liquidity.json') if d==seed['digest'] else dict(unavailable)
    lifecycle=read(store/'seed'/'lifecycle.json') if d==seed['digest'] else dict(unavailable)
    holders,holder_status=holder_evidence(store,d)
    out=assemble(c,a,holders,liquidity,lifecycle)
    ev=out['evidence'];ev.pop('digest')
    ev['seed_audit']=seed_audit
    ev['repairs']=repairs
    ev['payout_repairs']=payouts
    ev['delivery_repairs']=deliveries
    ev['holder_status']=holder_status
    ev['history_head']=h.head
    ev['digest']=digest(ev)
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve();store=a.store.resolve();docs=(ROOT/'docs').resolve()
    if any(out==x or x in out.parents or out in x.parents for x in (docs,store)):
        p.error('preview must be isolated from production and source data')
    if out.exists() and any(out.iterdir()):
        p.error('preview directory must be empty')
    b=bundle(store)
    out.mkdir(parents=True,exist_ok=True)
    for f in docs.iterdir():
        if f.is_file() and f.name!='snapshot.json':shutil.copy2(f,out/f.name)
    publish(b,out/'snapshot.json')
    print(f"UNPUBLISHED: {b['transfer_count']} transfers, {b['trace_count']} traces, {len(b['events'])} classified events; seed audit {b['evidence']['seed_audit']['attempted']}/{b['evidence']['seed_audit']['total_traces']}",flush=True)

if __name__=='__main__':main()
