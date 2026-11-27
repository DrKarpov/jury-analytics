"""Toncenter transport and transfer schema validation."""
import json, os, sys, time, base64, hashlib, urllib.request, urllib.parse
from pathlib import Path
BASE='https://toncenter.com/api/v3'
MASTER='Ef-_fgHqEczCswLpnBEoIvgyruJUvn_QDt5QRjecY8w3lr2i'
ROOT=Path(__file__).resolve().parents[1]

def address(value):
    if ':' in value:
        wc,h=value.split(':',1)
        if len(h)!=64: raise ValueError('invalid raw address')
        return str(int(wc))+':'+bytes.fromhex(h).hex()
    b=base64.urlsafe_b64decode(value+'='*((-len(value))%4))
    if len(b)!=36: raise ValueError('invalid address')
    import binascii
    if binascii.crc_hqx(b[:34],0)!=int.from_bytes(b[34:],'big'): raise ValueError('invalid address checksum')
    return str(int.from_bytes(b[1:2],'big',signed=True))+':'+b[2:34].hex()

def request(endpoint,params):
    headers={'Accept':'application/json', 'User-Agent':'JURY-Analytics/1.0'}
    if os.environ.get('TONCENTER_API_KEY'): headers['X-API-Key']=os.environ['TONCENTER_API_KEY']
    for attempt in range(5):
        try:
            url=BASE+'/'+endpoint+'?'+urllib.parse.urlencode(params,doseq=True)
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=35) as r:
                data=json.load(r)
                time.sleep(1.1)
                return data
        except Exception:
            if attempt==4: raise
            time.sleep(2**attempt)

def normalized(row):
    if address(row['jetton_master'])!=address(MASTER): raise ValueError('wrong token')
    if type(row['transaction_aborted']) is not bool: raise ValueError('missing abort status')
    amount=int(row['amount']); lt=int(row['transaction_lt']); stamp=int(row['transaction_now'])
    if amount<0 or lt<=0 or stamp<=0: raise ValueError('invalid transfer')
    tx=row['transaction_hash']; trace=row['trace_id']
    if not tx or not trace: raise ValueError('missing identifier')
    return {'tx':tx,'trace':trace,'lt':str(lt),'time':stamp,'source':address(row['source']),'destination':address(row['destination']),'amount_raw':str(amount),'aborted':row['transaction_aborted']}



def tonapi_request(endpoint,params):
    headers={'Accept':'application/json', 'User-Agent':'JURY-Analytics/1.0'}
    if os.environ.get('TONAPI_API_KEY'): headers['Authorization']='Bearer '+os.environ['TONAPI_API_KEY']
    url='https://tonapi.io/v2/'+endpoint+'?'+urllib.parse.urlencode(params,doseq=True)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=25) as r:
                data=json.load(r)
            time.sleep(1.1);return data
        except Exception:
            if attempt==2: raise
            time.sleep(2**attempt)
