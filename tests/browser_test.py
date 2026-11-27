"""Run with installed Playwright/Chromium; uses a synthetic snapshot only in intercepted test responses."""
import json, threading, functools, sys, os, hashlib, copy
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SimpleHTTPRequestHandler,directory=str(ROOT/'docs')))
threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_port}/'
address='0:'+'1'*64
cutoff=1795781400
sample={'schema':2,'token':'Ef-_fgHqEczCswLpnBEoIvgyruJUvn_QDt5QRjecY8w3lr2i','cutoff':cutoff,'source':'Toncenter v3','audit':'single_provider_unverified','events':[{'id':'a','trace':'a'*64,'time':cutoff-10,'kind':'buy','wallet':address,'amount_raw':'123456789000','quote_asset':'GRAM','quote_raw':'9000000000'},{'id':'b','trace':'b'*64,'time':cutoff-90000,'kind':'sell','wallet':address,'amount_raw':'20000000000','quote_asset':'GRAM','quote_raw':'3000000000'}],'unresolved':[{'trace':'c'*64,'time':cutoff-20,'kind':'unresolved'}]}
# Browser requires actual candidate digest and one-to-one raw transfer mapping.
for n,e in enumerate(sample['events'],1):
    e['id']=str(n)*64;e['transfer_tx']=str(n+2)*64
other='0:'+'2'*64
sample['transfers']=[{'tx':e['transfer_tx'],'trace':e['trace'],'lt':str(i+1),'time':e['time'],'source':other if e['kind']=='buy' else address,'destination':address if e['kind']=='buy' else other,'amount_raw':e['amount_raw'],'aborted':False} for i,e in enumerate(sample['events'])]
sample['transfers'].append({'tx':'5'*64,'trace':'c'*64,'lt':'3','time':cutoff-20,'source':other,'destination':address,'amount_raw':'1','aborted':True})
sample['trace_count']=3;sample['transfer_count']=3
sample['digest']=hashlib.sha256(json.dumps(sample,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

with sync_playwright() as p:
    browser=p.chromium.launch(**({'executable_path':os.environ['CHROMIUM_EXECUTABLE']} if os.environ.get('CHROMIUM_EXECUTABLE') else {}),args=['--no-sandbox'])
    for width in [320,375,393,768,1024,1440]:
        page=browser.new_page(viewport={'width':width,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base);page.locator('#notice').wait_for();page.wait_for_function("document.querySelector('#status').textContent==='Не индексировано'")
        assert page.locator('#metrics .metric').first.inner_text()=='—'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        page.route('**/snapshot.json',lambda route:route.fulfill(json=sample))
        page.reload();page.wait_for_function("document.querySelector('#status').textContent==='Не сверено'")
        assert page.locator('#metrics .metric').first.inner_text()=='1'
        assert page.locator('#metrics .metric').nth(1).inner_text()=='1'
        page.locator('#wallet-input').fill(address);page.locator('#search-button').click();assert page.locator('#wallet-detail .mini-metric').count()==9
        assert page.locator('#pnl-note').inner_text().startswith('Недоступно:')
        assert page.locator('#holder-metrics .mini-metric').first.locator('strong').inner_text()=='—'
        assert page.locator('#acc-table tbody tr').count()==1
        page.locator('[data-period="24h"]').click();assert page.locator('#metrics .metric').nth(1).inner_text()=='0'
        page.locator('#language').click();assert page.locator('#chart-title').inner_text()=='Trading activity'
        page.locator('#filters button').nth(3).click();assert page.locator('#transactions .empty').count()==1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        assert not errors,errors
        page.unroute('**/snapshot.json');page.route('**/snapshot.json',lambda route:route.fulfill(json={**sample,'cutoff':cutoff+1}));page.reload();page.wait_for_function("document.querySelector('#notice').textContent.includes('Cached version')");assert page.locator('#metrics .metric').first.inner_text()=='1'
        if width==393 and os.environ.get('JURY_TEST_SCREENSHOT'):page.screenshot(path=os.environ['JURY_TEST_SCREENSHOT'],full_page=True)
        page.close()
    browser.close()
server.shutdown()
print('6 viewports: empty data, fixture, range, language, filter, no horizontal overflow passed')
