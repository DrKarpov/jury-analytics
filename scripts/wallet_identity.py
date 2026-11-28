"""Bounded current owner/master getter cross-check; not historical ownership proof."""
import argparse,time,base64,json
from collections import Counter,defaultdict
from functools import partial
from pathlib import Path
from genesis_checkpoint import ANCHOR,validate_master,validate_receipt,signed
from indexer import TOKEN,hash_id,publish
from provider import address,request,tonapi_request,paired
from recovery import read
from wallet_stateinit import boc,require,prefix,stateinit_parts,inspect_record

def stack(response,n):
    require(response.get('success') is True and response.get('exit_code')==0,'getter not successful')
    s=response['stack'];require(len(s)==n,'unexpected getter stack size');return s

def cell(entry):
    require(entry.get('type') in ('cell','slice'),'unsupported stack cell')
    raw=entry.get('cell') or entry.get('slice')
    require(isinstance(raw,str),'missing stack cell')
    b=bytes.fromhex(raw) if raw.lower().startswith('b5ee9c72') else base64.b64decode(raw,validate=True)
    cells,i=boc(b);return cells[i]

def addr(entry):
    c=cell(entry);s=c['bits']
    require(len(s)==267 and not c['refs'] and s[:3]=='100','unsupported getter address')
    wc=int(s[3:11],2);wc=wc-256 if wc>=128 else wc
    return str(wc)+':'+f'{int(s[11:],2):064x}'

def validate(wallet,wallet_get,master_get,center):
    s=stack(wallet_get,4);owner=addr(s[1]);master=addr(s[2])
    require(master==TOKEN,'getter master differs from JURY')
    require(addr(stack(master_get,1)[0])==wallet,'master getter resolves a different wallet')
    require(s[0].get('type')=='num','unexpected balance type')
    v=s[0]['num'];balance=int(v,16) if v.startswith(('0x','-0x')) else int(v)
    require(balance>=0,'negative getter balance')
    code=cell(s[3])['hash'].hex()
    rows=center['jetton_wallets']
    require(len(rows)==1,'no unique indexed wallet')
    r=rows[0]
    require(address(r['address'])==wallet and address(r['owner'])==owner and address(r['jetton'])==TOKEN,'indexed identity differs from getters')
    require(hash_id(r['code_hash'])==code,'indexed code differs from getter code')
    return {'wallet':wallet,'owner':owner,'master':master,'code_hash':code}

def candidates(store):
    g=store/'genesis'/'v1';m=read(g/'master.json');messages=validate_master(m);out=defaultdict(list)
    for path in sorted((g/'receipts').glob('*.json')):
        r=read(path);q=validate_receipt(r,messages[path.stem],m['digest'])
        if int(q['recipient_at'])>ANCHOR:continue
        tx=r['raw']['center']['transactions'][0];raw=r['raw']['alternate']
        info={'message':q['message'],'tx':q['recipient_tx'],'historical_code':None,'prefix_owner_candidate':None,'canonical_hash_matches_wallet':None,'deployment_address_match':False,'stateinit_error':None}
        try:
            info['historical_code']=hash_id(tx['account_state_after']['code_hash'])
            a=tx['in_msg']['init_state'];b=raw['in_msg']['init']
            h,c,d,wrapper=stateinit_parts(base64.b64decode(a['body'],validate=True),center=True)
            h2,c2,d2,_=stateinit_parts(bytes.fromhex(b['boc']))
            require(hash_id(a['hash'])==wrapper and (h,c,d['hash'])==(h2,c2,d2['hash']),'provider init mismatch')
            owner,master,_=prefix(d)
            require(master==TOKEN,'prefix master mismatch')
            info.update(prefix_owner_candidate=owner,canonical_hash_matches_wallet=h==q['wallet'].split(':',1)[1],stateinit_code=c,derived_hash=h)
            historical=inspect_record(r,q)
            info.update(deployment_address_match=True,fixed_prefix_length=historical['fixed_prefix_length'],deployment_stateinit_hash=historical['stateinit_hash'])
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:info['stateinit_error']=str(e)
        out[q['wallet']].append(info)
    return m['digest'],out

def run(store,out,center=request,alternate=tonapi_request,limit=12,seconds=110):
    require(1<=limit<=30 and 1<=seconds<=180,'invalid budget')
    md,cs=candidates(store);started=int(time.time());deadline=time.monotonic()+seconds
    if center is request:center=partial(center,deadline=deadline)
    if alternate is tonapi_request:alternate=partial(alternate,deadline=deadline)
    records=[];failures=[];attempted=0;stop=None
    def getter(w,method,args=None):return alternate(f'blockchain/accounts/{w}/methods/{method}',{'args':args} if args else {})
    # Deterministic sample, not representative. First sample includes the manually reviewed wallet if present.
    sample=sorted(cs)
    reviewed='0:a5b9d637bbbf96262ed0e55ab69eca995caa495d0c01c6dfe3f443d38d8db9fc'
    if reviewed in cs:sample.remove(reviewed);sample.insert(0,reviewed)
    for w in sample[:limit]:
        if time.monotonic()>=deadline:break
        attempted+=1;raw={}
        try:
            raw['wallet_get'],raw['center']=paired(lambda:getter(w,'get_wallet_data'),lambda:center('jetton/wallets',{'address':w,'jetton_address':TOKEN,'limit':2}))
            owner=addr(stack(raw['wallet_get'],4)[1])
            raw['master_get']=getter(TOKEN,'get_wallet_address',[owner])
            r=validate(w,raw['wallet_get'],raw['master_get'],raw['center'])
        except OSError as e:
            stop=type(e).__name__;failures.append({'wallet':w,'reason':str(e),'raw':raw});break
        except (ValueError,TypeError,KeyError,AttributeError,IndexError) as e:
            failures.append({'wallet':w,'reason':str(e),'raw':raw});continue
        r['matching_historical_receipt_codes']=sum(x['historical_code']==r['code_hash'] for x in cs[w])
        r['matching_prefix_owners']=sum(x['prefix_owner_candidate']==r['owner'] for x in cs[w])
        records.append({'identity':r,'raw':raw})
    summary={'anchor':ANCHOR,'master_digest':md,'candidate_wallets':len(cs),'receipt_rows':sum(map(len,cs.values())),
             'receipts_with_decoded_prefix':sum(x['prefix_owner_candidate'] is not None for xs in cs.values() for x in xs),
             'receipts_with_canonical_address_match':sum(x['canonical_hash_matches_wallet'] is True for xs in cs.values() for x in xs),
             'receipts_with_valid_deployment_stateinit':sum(x['deployment_address_match'] for xs in cs.values() for x in xs),
             'sample_limit':limit,'attempted':attempted,'current_identity_matches':len(records),'failed':len(failures),
             'failure_reasons':dict(Counter(x['reason'] for x in failures)),'stop_reason':stop,'observed_from':started,'observed_to':int(time.time()),
             'scope':'current getter and indexed identity agreement for bounded sample; historical code/prefix overlap diagnostic only; no historical owner binding or balance proof'}
    publish(signed({**summary,'historical_candidates':dict(cs),'records':records,'failures':failures}),out)
    print('WALLET IDENTITY DIAGNOSTIC',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--limit',type=int,default=12);a=p.parse_args();run(a.store,a.out,limit=a.limit)
