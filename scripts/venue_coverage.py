"""Read-only inventory of provider-reported venues, not a proof of protocol coverage."""
import argparse,json
from collections import Counter
from pathlib import Path
from recovery import load_seed
from incremental import load_history
from repair_overlay import overlay
from payout_repair import overlay as payout_overlay
from indexer import digest,publish

def inventory(candidate):
    counts=Counter()
    for e in candidate['events']:
        if e['kind'] in ('buy','sell'):
            counts[e.get('venue') or 'unknown']+=1
    return {'candidate_digest':candidate['digest'],'cutoff':candidate['cutoff'],
            'classified_swaps':sum(counts.values()),'venue_labels':dict(sorted(counts.items())),
            'unresolved_traces':len(candidate['unresolved']),
            'scope':'provider-reported endpoint swaps; not independent proof of protocol coverage',
            'required_protocol_review':['moon.cx CPMM','moon.cx CLMM','STON.fi V1','STON.fi V2',
                                        'DeDust legacy','DeDust V2','Tonstakers route legs','other observed venues and aggregators'],
            'moon_omniston_relationship':'unverified'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    seed=load_seed(a.store);h=load_history(a.store,seed);overlay(a.store,seed,h);payout_overlay(a.store,seed,h)
    result=inventory(h.candidate());result['digest']=digest(result)
    a.out.parent.mkdir(parents=True,exist_ok=True);publish(result,a.out);print(json.dumps(result),flush=True)

if __name__=='__main__':main()
