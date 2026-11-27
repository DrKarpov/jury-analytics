"""Append-only primary history updates. The recovered seed and its audit remain immutable."""
import argparse, json, time
from collections import defaultdict
from pathlib import Path
from indexer import discover, fetch_actions, classify, digest, publish, OVERLAP, MASTER
from provider import request
from recovery import load_seed, read, check_candidate

MAX_WINDOW=3600
MAX_TRACES=300

def ordered(rows):
    return sorted(rows,key=lambda r:(r['time'],int(r['lt']),r['tx']))

class History:
    def __init__(self,seed):
        self.seed=seed['digest'];self.head=self.seed;self.cutoff=seed['cutoff']
        self.transfers={r['tx']:r for r in seed['transfers']}
        self.traces=defaultdict(list)
        self.events=defaultdict(list)
        self.actions_digests={}
        self.heads={self.head}
        self.unresolved={r['trace']:r for r in seed['unresolved']}
        for r in self.transfers.values():self.traces[r['trace']].append(r)
        for e in seed['events']:self.events[e['trace']].append(e)

    def apply(self,b):
        if b['seed_digest']!=self.seed or b['previous_digest']!=self.head or b['from_cutoff']!=self.cutoff:
            raise ValueError('update chain discontinuity')
        if digest({k:v for k,v in b.items() if k!='digest'})!=b['digest']:
            raise ValueError('update digest mismatch')
        end=b['to_cutoff']
        if not self.cutoff<end<=self.cutoff+MAX_WINDOW:raise ValueError('invalid update cutoff')
        seen=set();affected=set()
        for r in b['transfers']:
            tx=r['tx']
            if tx in seen or tx in self.transfers or not max(0,self.cutoff-OVERLAP)<=r['time']<=end:
                raise ValueError('duplicate or out-of-range appended transfer')
            seen.add(tx);affected.add(r['trace'])
        patches={r['trace']:r for r in b['patches']}
        if len(patches)!=len(b['patches']) or not affected<=patches.keys():raise ValueError('incomplete or duplicate trace patches')
        available=defaultdict(list)
        for r in b['transfers']:available[r['trace']].append(r)
        action_digests={}
        for trace,patch in patches.items():
            action_digests[trace]=digest(sorted(patch['actions'],key=lambda action:action['action_id']))
            rows=self.traces.get(trace,[])+available[trace]
            if not rows:raise ValueError('orphan trace patch')
            es,u=patch['events'],patch['unresolved']
            by_tx={r['tx']:r for r in rows}
            used=set()
            for e in es:
                tx=e['transfer_tx']
                if e['trace']!=trace or tx not in by_tx or tx in used or by_tx[tx]['aborted'] or not 0<e['time']<=end:
                    raise ValueError('invalid trace patch event')
                used.add(tx)
            if u is None:
                if len(used)!=len(rows):raise ValueError('missing unresolved evidence')
            elif u['trace']!=trace or u['transfer_count']!=len(rows)-len(used):
                raise ValueError('invalid unresolved patch')
        for r in b['transfers']:
            self.transfers[r['tx']]=r;self.traces[r['trace']].append(r)
        for trace,patch in patches.items():
            self.events[trace]=patch['events']
            if patch['unresolved'] is None:self.unresolved.pop(trace,None)
            else:self.unresolved[trace]=patch['unresolved']
        self.actions_digests.update(action_digests)
        self.cutoff=end;self.head=b['digest']
        self.heads.add(self.head)

    def candidate(self):
        c={'schema':2,'token':MASTER,'cutoff':self.cutoff,'source':'Toncenter v3','audit':'single_provider_unverified',
           'transfer_count':len(self.transfers),'trace_count':len(self.traces),
           'transfers':ordered(self.transfers.values()),
           'events':sorted((e for es in self.events.values() for e in es),key=lambda e:(e['time'],e['id'])),
           'unresolved':sorted(self.unresolved.values(),key=lambda u:(u['time'],u['trace']))}
        c['digest']=digest(c)
        return check_candidate(c,c['digest'])

def load_history(store,seed=None):
    h=History(seed if seed is not None else load_seed(store))
    for path in sorted((store/'updates').glob('batch-*.json')):
        b=read(path)
        if path.name!=f"batch-{b['from_cutoff']:012d}-{b['to_cutoff']:012d}.json":
            raise ValueError('update file identity mismatch')
        h.apply(b)
    return h

def build_update(h,fetch,target,max_traces=MAX_TRACES):
    """Re-read overlap; append late arrivals explicitly, never delete or change saved transfers."""
    start=max(0,h.cutoff-OVERLAP)
    end=min(target,h.cutoff+MAX_WINDOW)
    if end<=h.cutoff:return None
    pending={t for t,u in h.unresolved.items() if u['time']>=start and
             ('pending_or_invalid_time' in u.get('reasons',[]) or not h.events.get(t))}
    while True:
        observed={tx:r for tx,(r,raw) in discover(fetch,start,end).items()}
        existing={tx:r for tx,r in h.transfers.items() if start<=r['time']<=h.cutoff}
        if any(observed.get(tx)!=r for tx,r in existing.items()):
            raise ValueError('overlap missing or changed saved transfer; refusing checkpoint')
        for tx,r in observed.items():
            if tx in h.transfers and h.transfers[tx]!=r:raise ValueError('saved transfer changed')
        new=[r for tx,r in observed.items() if tx not in h.transfers]
        affected={r['trace'] for r in new}
        if len(affected)<=max_traces:break
        if end==h.cutoff+1:raise ValueError('new trace batch exceeds limit at minimum window')
        end=h.cutoff+max(1,(end-h.cutoff)//2)
        print(f'Reducing update window to {end-h.cutoff}s',flush=True)
    # Recheck recent unresolved traces within remaining budget; new transfers always take priority.
    touched=sorted(affected|set(sorted(pending-affected)[:max(0,max_traces-len(affected))]))
    grouped=defaultdict(list)
    for r in new:grouped[r['trace']].append(r)
    patches=[]
    for i in range(0,len(touched),20):
        ids=touched[i:i+20]
        actions=fetch_actions(fetch,ids)
        for t in ids:
            rows=h.traces.get(t,[])+grouped[t]
            if not actions[t] and h.events.get(t):
                raise ValueError('provider lost previously classified trace actions')
            es,u=classify(t,actions[t],rows,end)
            patches.append({'trace':t,'actions':actions[t],'events':es,'unresolved':u})
        print(f'Incremental trace classification: {min(i+20,len(touched))}/{len(touched)}',flush=True)
    b={'version':1,'seed_digest':h.seed,'previous_digest':h.head,'from_cutoff':h.cutoff,'to_cutoff':end,
       'transfers':ordered(new),'patches':patches,'late_transfers':sum(r['time']<=h.cutoff for r in new)}
    b['digest']=digest(b)
    return b

def advance(store, fetch=request, target=None, seed=None, max_windows=1):
    if not 1 <= max_windows <= 3:
        raise ValueError('invalid catch-up window limit')
    h = load_history(store, seed)
    target = int(time.time()) - 180 if target is None else target
    deadline = time.monotonic() + 240

    def bounded(endpoint, params):
        if time.monotonic() >= deadline:
            raise TimeoutError('incremental request budget exhausted')
        if fetch is request:
            return request(endpoint, params, deadline=deadline)
        return fetch(endpoint, params)

    windows = new_transfers = late_transfers = 0
    stop_reason = None
    for _ in range(max_windows):
        try:
            batch = build_update(h, bounded, target)
        except OSError as error:
            if not windows:
                raise
            stop_reason = type(error).__name__
            break
        if batch is None:
            break
        h.apply(batch)
        h.candidate()
        folder = store / 'updates'
        folder.mkdir(exist_ok=True)
        path = folder / f"batch-{batch['from_cutoff']:012d}-{batch['to_cutoff']:012d}.json"
        if path.exists():
            raise ValueError('immutable update already exists')
        publish(batch, path)
        windows += 1
        new_transfers += len(batch['transfers'])
        late_transfers += batch['late_transfers']

    report = {'status': 'primary_unverified', 'seed_digest': h.seed, 'head_digest': h.head,
              'cutoff': h.cutoff, 'transfer_count': len(h.transfers), 'trace_count': len(h.traces),
              'windows': windows, 'new_transfers': new_transfers, 'late_transfers': late_transfers,
              'remaining_seconds': max(0, target - h.cutoff), 'stop_reason': stop_reason,
              'scope': 'primary transfer discovery; seed audit does not verify updated history'}
    publish(report, store / 'update-status.json')
    print(json.dumps(report), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--max-windows', type=int, default=1)
    args = parser.parse_args()
    advance(args.store, max_windows=args.max_windows)


if __name__ == '__main__':
    main()
