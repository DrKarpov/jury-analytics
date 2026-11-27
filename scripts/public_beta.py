"""Build the explicitly provisional public artifact, never publish working datasets."""
import argparse,shutil
from pathlib import Path
from indexer import ROOT,digest,publish
from persistent_preview import bundle

ASSETS=('index.html','styles.css','telegram.svg','app.mjs','analytics.mjs','integrity.mjs','wallets.mjs','wallet-ui.mjs','cost-basis.mjs')
def build(store,out):
    store=store.resolve();out=out.resolve();docs=(ROOT/'docs').resolve()
    if any(out==x or x in out.parents or out in x.parents for x in (store,docs)):
        raise ValueError('isolated output required')
    if out.exists() and any(out.iterdir()):raise ValueError('nonempty output directory')
    b=bundle(store);ev=b['evidence']
    if not b['cutoff'] or not b['transfer_count'] or ev['swap_audit']['checked']!=0 or ev['swap_audit']['status']!='partial':
        raise ValueError('unexpected beta snapshot')
    if any(ev[k]['conflicts'] for k in ('repairs','payout_repairs','delivery_repairs')):
        raise ValueError('repair conflict blocks publication')
    ev['mode']='public_beta';ev['digest']=digest({k:v for k,v in ev.items() if k!='digest'})
    out.mkdir(parents=True,exist_ok=True)
    for name in ASSETS:shutil.copy2(docs/name,out/name)
    publish(b,out/'snapshot.json')
    print(f"PUBLIC BETA CANDIDATE: {b['transfer_count']} transfers, {b['trace_count']} traces, {len(b['events'])} classified operations, cutoff {b['cutoff']}",flush=True)
    return b

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();build(a.store,a.out)
