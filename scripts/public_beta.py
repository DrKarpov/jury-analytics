"""Build the explicitly provisional public artifact, never publish working datasets."""
import argparse,re,shutil
from pathlib import Path
from indexer import ROOT,digest,publish
from persistent_preview import bundle

ASSETS=('index.html','styles.css','telegram.svg','app.mjs','analytics.mjs','integrity.mjs','wallets.mjs','wallet-ui.mjs','cost-basis.mjs')
def build(store,out,source_sha=None,data_sha=None):
    store=store.resolve();out=out.resolve();docs=(ROOT/'docs').resolve()
    if any(out==x or x in out.parents or out in x.parents for x in (store,docs)):
        raise ValueError('isolated output required')
    if out.exists() and any(out.iterdir()):raise ValueError('nonempty output directory')
    b=bundle(store);ev=b['evidence']
    if not b['cutoff'] or not b['transfer_count'] or ev['swap_audit']['checked']!=0 or ev['swap_audit']['status']!='partial':
        raise ValueError('unexpected beta snapshot')
    if any(ev[k]['conflicts'] for k in ('repairs','payout_repairs','delivery_repairs')):
        raise ValueError('repair conflict blocks publication')
    if source_sha is not None or data_sha is not None:
        if not all(re.fullmatch(r'[a-f0-9]{40}', sha or '') for sha in (source_sha,data_sha)):
            raise ValueError('release provenance needs both Git commit SHAs')
        ev['release']={'source_sha':source_sha,'data_sha':data_sha}
    ev['mode']='public_beta';ev['digest']=digest({k:v for k,v in ev.items() if k!='digest'})
    out.mkdir(parents=True,exist_ok=True)
    for name in ASSETS:shutil.copy2(docs/name,out/name)
    publish(b,out/'snapshot.json')
    publish({'version':1,'cutoff':b['cutoff'],'snapshot_digest':b['digest'],
             'evidence_digest':ev['digest']},out/'release.json')
    print(f"PUBLIC BETA CANDIDATE: {b['transfer_count']} transfers, {b['trace_count']} traces, {len(b['events'])} classified operations, cutoff {b['cutoff']}",flush=True)
    return b

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--source-sha');p.add_argument('--data-sha');a=p.parse_args();build(a.store,a.out,a.source_sha,a.data_sha)
