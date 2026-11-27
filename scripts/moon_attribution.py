"""Find protocol evidence independently of swap labels. Do not infer frontend attribution."""
import argparse,json,time
from collections import Counter,defaultdict
from pathlib import Path
from indexer import ROOT,digest,publish,hash_id
from provider import address,request
from recovery import load_seed,read
from incremental import load_history
from repair_overlay import overlay
from payout_repair import overlay as payout_overlay
from delivery_repair import overlay as delivery_overlay

def registry():
    r=read(ROOT/'config/moon-registry.json')
    hashes={hash_id(k):v for k,v in r['hashes'].items()}
    hashes[hash_id(r['legacy_hash_base64'])]='MoonPoolLegacy'
    return hashes,{address(k):v for k,v in r['addresses'].items()}

def scan(h,known,observations):
    out=defaultdict(set)
    for t,rows in h.traces.items():
        for r in rows:
            for a in (r['source'],r['destination']):
                if a in known:out[t].add((a,known[a],'catalog_address'))
                if a in observations:out[t].add((a,observations[a],'current_code_hash'))
    return out

def referral_fields(obj,path=''):
    """Return explicit decoded field names only, not proof of ownership."""
    if isinstance(obj,dict):
        for k,v in obj.items():
            p=path+'.'+k if path else k
            if k.lower() in ('referral','referral_address','referrer','referrer_address','partner_address','platform_tag') and isinstance(v,str):
                try:yield p,address(v)
                except (ValueError,TypeError):pass
            elif isinstance(v,(dict,list)):yield from referral_fields(v,p)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):yield from referral_fields(v,f'{path}[{i}]')

def run(store,fetch=request,limit=1000):
    seed=load_seed(store);h=load_history(store,seed);overlay(store,seed,h);payout_overlay(store,seed,h);delivery_overlay(store,seed,h)
    hashes,known=registry()
    accounts=Counter(a for r in h.transfers.values() for a in (r['source'],r['destination']))
    selected=sorted(accounts,key=lambda a:(-accounts[a],a))[:limit]
    observations={};checked=set();unavailable=set();state_rows=[]
    for i in range(0,len(selected),25):
        chunk=selected[i:i+25]
        try:
            response=fetch('accountStates',{'address':chunk,'include_boc':'false'})
            rows=response['accounts']
            seen=set()
            for r in rows:
                a=address(r['address'])
                if a not in chunk or a in seen:raise ValueError('account response identity mismatch')
                seen.add(a)
                code=r.get('code_hash')
                if code:
                    code=hash_id(code)
                    if code in hashes:observations[a]=hashes[code]
                state_rows.append({'address':a,'code_hash':code,'last_transaction_lt':r.get('last_transaction_lt')})
            checked.update(seen);unavailable.update(set(chunk)-seen)
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as e:
            print('Account observation stopped:',type(e).__name__,flush=True);break
    matches=scan(h,known,observations)
    refs=defaultdict(set);raw_count=0;opcode_hints=set();historical_candidates={}
    for p in sorted((store/'triage-raw'/'v1').glob('*.json')):
        r=read(p)
        if r['digest']!=digest({k:v for k,v in r.items() if k!='digest'}):raise ValueError('raw evidence checksum')
        t=r['trace'];raw_count+=1
        from discrepancy import tree_index
        tree_index(r['tree'],t)
        stack=[r['tree']]
        while stack:
            n=stack.pop();tx=n['transaction'];m=tx.get('in_msg') or {}
            for _,a in referral_fields(m.get('decoded_body',{})):refs[a].add(t)
            if str(m.get('op_code','')).lower() in ('0xb37a900b','0xcb7f38d6'):opcode_hints.add(t)
            if any('moon' in x.lower() for x in n.get('interfaces',[]) if isinstance(x,str)) or str(m.get('op_code','')).lower() in ('0xb37a900b','0xcb7f38d6'):
                historical_candidates[hash_id(tx['hash'])]=t
            stack.extend(n.get('children',[]))
    historical=[]
    ids=sorted(historical_candidates)
    for i in range(0,len(ids),20):
        import base64
        chunk=ids[i:i+20]
        try:
            rows=fetch('transactions',{'hash':[base64.b64encode(bytes.fromhex(x)).decode() for x in chunk],'limit':len(chunk)})['transactions']
            seen=set()
            for r in rows:
                tx=hash_id(r['hash'])
                if tx not in chunk or tx in seen:raise ValueError('unexpected historical tx')
                seen.add(tx)
                before=(r.get('account_state_before') or {}).get('code_hash')
                if before and hash_id(before) in hashes:
                    historical.append({'trace':historical_candidates[tx],'tx':tx,'account':address(r['account']),'role':hashes[hash_id(before)],'code_hash':hash_id(before)})
        except (OSError,ValueError,KeyError,TypeError,AttributeError):break
    report={'candidate_digest':h.candidate()['digest'],'cutoff':h.cutoff,'observed_at':int(time.time()),
            'unique_transfer_counterparties':len(accounts),'selected':len(selected),'current_state_checked':len(checked),
            'unavailable_selected':len(unavailable),'current_moon_code_matches':observations,
            'transfer_traces_with_moon_contract_evidence':len(matches),'trace_matches':[
                {'trace':t,'accounts':[{'address':a,'role':role,'evidence':kind} for a,role,kind in sorted(v)]} for t,v in sorted(matches.items())],
            'raw_trees_checked':raw_count,'moon_opcode_hint_traces':len(opcode_hints),
            'historical_code_matches':historical,
            'unattributed_referrals':[{'address':a,'traces':len(ts)} for a,ts in sorted(refs.items(),key=lambda x:(-len(x[1]),x[0]))],
            'scope':'current account code or catalog address matches are protocol candidates, not historical swap or frontend attribution; raw samples are non-exhaustive',
            'frontend_attribution':'unverified'}
    return report,state_rows

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    r,states=run(a.store);a.out.mkdir(parents=True,exist_ok=True)
    r['digest']=digest(r);publish(r,a.out/'report.json');publish(states,a.out/'account-observations.json')
    print(json.dumps({k:v for k,v in r.items() if k not in ('trace_matches','unattributed_referrals')}),flush=True)
