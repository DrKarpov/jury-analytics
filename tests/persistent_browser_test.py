"""Smoke test against the actual persistent preview; never intercept snapshot requests."""
import sys, json, threading, functools
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright, expect
root=Path(sys.argv[1]).resolve()
snapshot=json.loads((root/'snapshot.json').read_text())
assert snapshot['cutoff'] and snapshot['transfer_count']>0
counts=[sum(e['kind']==k for e in snapshot['events']) for k in ('buy','sell','transfer')]
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SimpleHTTPRequestHandler,directory=str(root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(args=['--no-sandbox'])
        for width in (320,393,1440):
            page=browser.new_page(viewport={'width':width,'height':900})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            expect(page.locator('#status')).to_have_text('Не сверено',timeout=30000)
            expect(page.locator('#staging-badge')).to_be_visible()
            expect(page.locator('#audit-line')).to_contain_text('Сверка исходной истории')
            for i,n in enumerate(counts):
                raw=page.locator('#metrics .metric').nth(i).inner_text()
                assert int(''.join(raw.split()))==n,(i,raw,n)
            assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'),width
            page.locator('#language').click()
            expect(page.locator('#audit-line')).to_contain_text('Seed history audit')
            assert not errors,errors
            page.close()
        browser.close()
finally:server.shutdown()
print('Actual persistent snapshot rendered at 320, 393 and 1440 pixels')
