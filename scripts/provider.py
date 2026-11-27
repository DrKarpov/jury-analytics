"""Toncenter transport and transfer schema validation."""
import json, os, time, base64, random, urllib.error, urllib.request, urllib.parse
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
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

def retry_delay(error, attempt):
    delay = 2 ** attempt + random.uniform(0, 0.25)
    value = error.headers.get('Retry-After') if isinstance(error, urllib.error.HTTPError) and error.headers else None
    if value:
        try:
            requested = int(value) if value.isdigit() else parsedate_to_datetime(value).timestamp() - time.time()
            delay = max(delay, requested)
        except (TypeError, ValueError, OverflowError):
            pass
    return delay


def fetch_json(url, headers, attempts, timeout, deadline):
    deadline = time.monotonic() + 75 if deadline is None else deadline
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('provider request budget exhausted')
        try:
            with urllib.request.urlopen(req, timeout=min(timeout, remaining)) as response:
                payload = json.load(response)
        except (OSError, IncompleteRead) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429) and not 500 <= error.code < 600:
                raise
            delay = retry_delay(error, attempt)
            if attempt == attempts - 1 or time.monotonic() + delay >= deadline:
                raise
            time.sleep(delay)
        else:
            time.sleep(min(1.1, max(0, deadline - time.monotonic())))
            return payload


def request(endpoint, params, *, deadline=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'JURY-Analytics/1.0'}
    if os.environ.get('TONCENTER_API_KEY'):
        headers['X-API-Key'] = os.environ['TONCENTER_API_KEY']
    url = BASE + '/' + endpoint + '?' + urllib.parse.urlencode(params, doseq=True)
    return fetch_json(url, headers, attempts=5, timeout=35, deadline=deadline)


def normalized(row):
    if address(row['jetton_master'])!=address(MASTER): raise ValueError('wrong token')
    if type(row['transaction_aborted']) is not bool: raise ValueError('missing abort status')
    amount=int(row['amount']); lt=int(row['transaction_lt']); stamp=int(row['transaction_now'])
    if amount<0 or lt<=0 or stamp<=0: raise ValueError('invalid transfer')
    tx=row['transaction_hash']; trace=row['trace_id']
    if not tx or not trace: raise ValueError('missing identifier')
    return {'tx':tx,'trace':trace,'lt':str(lt),'time':stamp,'source':address(row['source']),'destination':address(row['destination']),'amount_raw':str(amount),'aborted':row['transaction_aborted']}



def tonapi_request(endpoint, params, *, deadline=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'JURY-Analytics/1.0'}
    if os.environ.get('TONAPI_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['TONAPI_API_KEY']
    url = 'https://tonapi.io/v2/' + endpoint + '?' + urllib.parse.urlencode(params, doseq=True)
    return fetch_json(url, headers, attempts=3, timeout=25, deadline=deadline)
