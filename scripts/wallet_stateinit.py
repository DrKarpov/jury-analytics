"""Offline StateInit identity diagnostics from saved two-provider genesis receipts.

Only ordinary level-zero BOCs are supported. Unknown wallet layout, malformed BOCs,
different provider roots and address/code mismatches remain unresolved. No ledger
or owner assignment is installed. See TON docs foundations/serialization/cells,boc.
"""
import argparse,base64,hashlib,json
from collections import Counter,defaultdict
from pathlib import Path
from genesis_checkpoint import ANCHOR,validate_master,validate_receipt,signed
from indexer import TOKEN,hash_id,publish
from recovery import read

def require(ok,why):
    if not ok:raise ValueError(why)

def crc32c(raw):
    crc=0xffffffff
    for n in raw:
        crc^=n
        for _ in range(8):crc=(crc>>1)^(0x82f63b78 if crc&1 else 0)
    return (crc^0xffffffff).to_bytes(4,'little')

def boc(raw):
    require(len(raw)>=10 and raw[:4]==bytes.fromhex('b5ee9c72'),'unsupported BOC magic')
    flags=raw[4];size=flags&7;offset=raw[5];idx=bool(flags&128);crc=bool(flags&64)
    require(1<=size<=4 and 1<=offset<=8 and not flags&0x38,'unsupported BOC flags')
    if crc:
        require(crc32c(raw[:-4])==raw[-4:],'BOC CRC mismatch')
        raw=raw[:-4]
    pos=6
    def take(n):
        nonlocal pos
        require(n>=0 and pos+n<=len(raw),'truncated BOC')
        v=raw[pos:pos+n];pos+=n;return v
    def num(n):return int.from_bytes(take(n),'big')
    count,roots,absent,total=num(size),num(size),num(size),num(offset)
    require(0<count<=10000 and roots==1 and absent==0,'unsupported BOC cardinality')
    root=num(size);require(root<count,'invalid root index')
    index=[num(offset) for _ in range(count)] if idx else None
    require(pos+total==len(raw),'BOC size mismatch')
    start=pos;cells=[];ends=[]
    for i in range(count):
        d1,d2=take(2);require(d1<=4,'unsupported nonordinary or levelled cell')
        data=take((d2+1)//2);bits=''.join(f'{b:08b}' for b in data)
        if d2&1:
            require(data and data[-1]!=0 and data[-1]!=128,'invalid top-up')
            bits=bits[:bits.rfind('1')]
        require(len(bits)<=1023 and d2==len(bits)//8+(len(bits)+7)//8,'bad cell descriptor')
        refs=[num(size) for _ in range(d1)]
        require(all(i<r<count for r in refs),'invalid cell reference order')
        cells.append({'bits':bits,'refs':refs,'repr':bytes([d1,d2])+data})
        ends.append(pos-start)
    require(pos==len(raw),'extra cell bytes')
    if index is not None:require(index==ends,'BOC index mismatch')
    for c in reversed(cells):
        children=[cells[i] for i in c['refs']]
        c['depth']=1+max(x['depth'] for x in children) if children else 0
        require(c['depth']<=1024,'cell depth exceeded')
        c['hash']=hashlib.sha256(c['repr']+b''.join(x['depth'].to_bytes(2,'big') for x in children)+b''.join(x['hash'] for x in children)).digest()
    return cells,root

def stateinit_parts(raw,*,center=False):
    cells,i=boc(raw);root=cells[i]
    # TL-B StateInit: fixed_prefix_length:(Maybe (## 5)), special,
    # code, data, library. The observed Toncenter 1010000110 is
    # Some(8), no special, code+data, no library. TonAPI omits
    # this field in its serialized view. Preserve the full root hash.
    allowed=('00110','1010000110') if center else ('00110',)
    require(root['bits'] in allowed and len(root['refs'])==2,'unsupported StateInit structure')
    code,data=(cells[j] for j in root['refs'])
    # Normalized unprefixed hash is used only to compare code/data
    # across providers. It is not the sharded deployment address hash.
    h=hashlib.sha256(bytes.fromhex('020134')+code['depth'].to_bytes(2,'big')+data['depth'].to_bytes(2,'big')+code['hash']+data['hash']).hexdigest()
    return h,code['hash'].hex(),data,root['hash'].hex()

def decode_stateinit(raw):
    return stateinit_parts(raw)[:3]

def deployment_prefix_length(raw):
    cells,i=boc(raw);root=cells[i]
    require(len(root['refs'])==2,'unsupported StateInit structure')
    if root['bits']=='00110':return 0
    if root['bits']=='1010000110':return 8
    raise ValueError('unsupported StateInit structure')

def deployment_address_matches(stateinit_hash,wallet,depth):
    # TON protocol: only the explicitly declared high-order prefix may
    # differ; never compare a truncated hash or guess depth from address.
    require(depth in (0,8),'unsupported fixed_prefix_length')
    wc,account=wallet.split(':',1)
    require(wc=='0' and len(account)==64,'unsupported recipient workchain/address')
    require(len(stateinit_hash)==64,'invalid StateInit hash length')
    mask=(1<<(256-depth))-1
    return (int(stateinit_hash,16)&mask)==(int(account,16)&mask)

def owner_prefix_matches(owner,wallet,depth):
    if depth==0:return True
    ow,oh=owner.split(':',1);ww,wh=wallet.split(':',1)
    return ow==ww and int(oh,16)>>(256-depth)==int(wh,16)>>(256-depth)

def prefix(data):
    # Observed JURY initial-data prefix: zero VarUInteger16, std owner, std master.
    # The suffix and executable semantics are not certified by this diagnostic.
    bits=data['bits'];require(len(bits)>=538 and bits[:4]=='0000','unsupported initial data prefix')
    def address_at(off):
        v=bits[off:off+267];require(v[:3]=='100','unsupported initial address')
        wc=int(v[3:11],2);wc=wc-256 if wc>=128 else wc
        return str(wc)+':'+f'{int(v[11:],2):064x}'
    return address_at(4),address_at(271),bits[538:]

def inspect_record(record,proof):
    c=record['raw']['center']['transactions'][0];a=record['raw']['alternate']
    cm=c['in_msg'];am=a['in_msg']
    ci=cm.get('init_state');ai=am.get('init')
    require(isinstance(ci,dict) and ci.get('body') and isinstance(ai,dict) and ai.get('boc'),'missing dual StateInit')
    center_boc=base64.b64decode(ci['body'],validate=True)
    ch,cc,cd,wrapper=stateinit_parts(center_boc,center=True)
    depth=deployment_prefix_length(center_boc)
    ah,ac,ad=decode_stateinit(bytes.fromhex(ai['boc']))
    require((ch,cc,cd['hash'])==(ah,ac,ad['hash']),'provider StateInit mismatch')
    require(ci.get('hash') and hash_id(ci['hash'])==wrapper,'provider declared StateInit hash mismatch')
    require(deployment_address_matches(wrapper,proof['wallet'],depth),'StateInit deployment suffix does not match recipient address')
    require(cc==hash_id(c['account_state_after']['code_hash']),'historical code differs from StateInit')
    owner,master,tail=prefix(cd)
    require(master==TOKEN,'initial data master differs from JURY')
    require(owner_prefix_matches(owner,proof['wallet'],depth),'JURY owner shard prefix differs')
    return {'wallet':proof['wallet'],'owner_candidate':owner,'master_candidate':master,'stateinit_hash':wrapper,'unprefixed_comparison_hash':ch,'center_serialization_hash':wrapper,'fixed_prefix_length':depth,'code_hash':cc,'data_hash':cd['hash'].hex(),'uninterpreted_suffix_bits':len(tail),'uninterpreted_suffix':tail,'data_refs':len(cd['refs']),'message':proof['message'],'recipient_tx':proof['recipient_tx']}

def run(store,out):
    g=store/'genesis'/'v1';master=read(g/'master.json');messages=validate_master(master)
    reasons=Counter();records=[];by_wallet=defaultdict(list);roots=set();failures=[]
    for p in sorted((g/'receipts').glob('*.json')):
        record=read(p);proof=validate_receipt(record,messages[p.stem],master['digest'])
        if int(proof['recipient_at'])>ANCHOR:continue
        roots.add(proof['wallet'])
        try:r=inspect_record(record,proof)
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as e:
            reason=str(e);reasons[reason]+=1;failures.append({'message':proof['message'],'wallet':proof['wallet'],'reason':reason});continue
        records.append(r);by_wallet[r['wallet']].append(r)
    conflicts=[];consistent={}
    for w,rs in sorted(by_wallet.items()):
        identities={(r['owner_candidate'],r['master_candidate'],r['code_hash'],r['data_hash']) for r in rs}
        if len(identities)!=1:conflicts.append(w)
        else:consistent[w]=rs[0]
    summary={'cutoff':ANCHOR,'master_digest':master['digest'],'receipts_examined':len(records)+len(failures),'recipient_wallets':len(roots),'matching_stateinit_receipts':len(records),'consistent_wallet_candidates':len(consistent),'conflicting_wallets':len(conflicts),'wallets_without_consistent_candidate':len(roots)-len(consistent),'failure_reasons':dict(reasons),'fixed_prefix_lengths':dict(Counter(str(x['fixed_prefix_length']) for x in records)),'scope':'offline saved mint receipt StateInit/address/code and candidate data prefix, not executable layout certification, full historical owner binding, balance or economic classification'}
    publish(signed({**summary,'records':records,'failures':failures,'conflicts':conflicts}),out)
    print('STATEINIT DIAGNOSTIC',json.dumps(summary,sort_keys=True),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--store',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.store,a.out)
