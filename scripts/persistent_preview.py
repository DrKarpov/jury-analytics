"""Build an unpublished preview from a pinned, validated persistent data checkout."""
import argparse, shutil
from pathlib import Path
from indexer import ROOT, digest, publish
from recovery import load_seed, load_progress, read
from incremental import load_history
from current_audit import coverage
from preview import assemble
from holder_state import evidence as holder_evidence
from repair_overlay import overlay
from payout_repair import overlay as payout_overlay
from delivery_repair import overlay as delivery_overlay
from revision_evidence import lineage
from arbitrage import overlay as arbitrage_overlay

def corrected_history(store, seed=None):
    seed=load_seed(store) if seed is None else seed
    h=load_history(store,seed)
    repairs=overlay(store,seed,h)
    payouts,_=payout_overlay(store,seed,h)
    deliveries,_=delivery_overlay(store,seed,h)
    arbitrage_overlay(h,store)
    return h, repairs, payouts, deliveries

def bundle(store):
    seed=load_seed(store)
    h, repairs, payouts, deliveries = corrected_history(store, seed)
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
    resolved=repairs['active_resolutions']+payouts['active_resolutions']+deliveries['active_resolutions']
    if resolved>seed_audit['mismatch']:raise ValueError('repair count exceeds audit mismatches')
    seed_audit['reconciled_mismatches']=resolved
    seed_audit['remaining_mismatches']=seed_audit['mismatch']-resolved
    seed_audit['matched_after_repairs']=seed_audit['matched']+resolved
    ev['seed_audit']=seed_audit
    ev['current_trace_audit']=coverage(store,h)
    ev['repairs']=repairs
    ev['payout_repairs']=payouts
    ev['delivery_repairs']=deliveries
    ev['holder_status']=holder_status
    from arbitrage import evidence_records, verify, candidate_pairs
    # Replay on uncorrected history for a stable proof summary; existing repair overlays remain separate.
    base=load_history(store,seed)
    cycles=[verify(r,base.traces[r['trace']],base.events[r['trace']])[1] for r in evidence_records(store) if r['trace'] in base.traces]
    ev['arbitrage']={'verified_cycles':cycles,'additional_candidate_cycles':sum(bool(candidate_pairs(rows,h.events.get(t,[]))) for t,rows in h.traces.items()),'scope':'wallet cashflow for verified circular swaps; missing DEX quotes excluded from volume'}
    ev['history_head']=h.head
    ev['revision_lineage']=lineage(store,seed,h)
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
