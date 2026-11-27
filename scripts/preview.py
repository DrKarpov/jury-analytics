"""Bundle a single staging run into an explicitly UNPUBLISHED preview directory."""
import argparse, json, shutil
from pathlib import Path
from indexer import digest, publish, ROOT, MASTER, integer
from provider import address

def assemble(candidate,audit,holders,liquidity,lifecycle):
    if candidate.get('schema')!=2 or candidate.get('token')!=MASTER or not candidate.get('cutoff'): raise ValueError('wrong candidate')
    h=candidate['digest']
    if digest({k:v for k,v in candidate.items() if k!='digest'})!=h: raise ValueError('candidate digest mismatch')
    if audit.get('snapshot_digest')!=h: raise ValueError('audit belongs to another snapshot')
    if liquidity.get('candidate_digest')!=h or lifecycle.get('candidate_digest')!=h or holders.get('candidate_digest')!=h: raise ValueError('mixed staging runs')
    if lifecycle.get('cutoff',candidate['cutoff'])!=candidate['cutoff']: raise ValueError('lifecycle cutoff mismatch')
    observation=None
    if 'owners' in holders:
        owners=holders['owners']; seen=set()
        for r in owners:
            a=address(r['owner'])
            if a in seen or integer(r['balance_raw'])<=0: raise ValueError('invalid holder observation')
            seen.add(a)
        if sum(integer(r['balance_raw']) for r in owners)!=integer(holders['supply_raw']) or len(owners)!=holders['owner_count']: raise ValueError('holder sum/count mismatch')
        observation=holders
    evidence={'mode':'staging','candidate_digest':h,'swap_audit':audit,'holders':observation,'liquidity':liquidity,'lifecycle':lifecycle}
    evidence['digest']=digest(evidence)
    return {**candidate,'evidence':evidence}

def main():
    p=argparse.ArgumentParser();p.add_argument('--staging',type=Path,default=ROOT/'data/staging');p.add_argument('--out',type=Path,default=ROOT/'data/preview');a=p.parse_args()
    src=a.staging.resolve();out=a.out.resolve();docs=(ROOT/'docs').resolve()
    if out==docs or docs in out.parents or out in docs.parents or out==src or out in src.parents or src in out.parents: p.error('preview must be separate from production and staging paths')
    bundle=assemble(*(json.loads((src/f'{k}.json').read_text()) for k in ['candidate','swap-audit','holders','liquidity','lifecycle']))
    out.mkdir(parents=True,exist_ok=True)
    for f in docs.iterdir():
        if f.is_file() and f.name!='snapshot.json': shutil.copy2(f,out/f.name)
    publish(bundle,out/'snapshot.json');print('UNPUBLISHED preview:',out)
if __name__=='__main__':main()
