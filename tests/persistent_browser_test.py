"""Smoke test against the actual persistent preview; never intercept snapshot requests."""
import sys, json, threading, functools, time
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright, expect
root=Path(sys.argv[1]).resolve()
widths=(320,375,393,430,768,1024,1440)
has_manifest=(root/'release.json').is_file()
snapshot=json.loads((root/'snapshot.json').read_text())
assert snapshot['cutoff'] and snapshot['transfer_count']>0
counts=[sum(e['kind']==k for e in snapshot['events']) for k in ('buy','sell','transfer')]
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SimpleHTTPRequestHandler,directory=str(root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(args=['--no-sandbox'])
        for width in widths:
            page=browser.new_page(viewport={'width':width,'height':900})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            requests=[]
            page.on('request',lambda request:requests.append(request.url))
            started=time.perf_counter()
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            expect(page.locator('#status')).to_have_text('Не сверено',timeout=30000)
            elapsed=time.perf_counter()-started
            print(f'{width}px cold local render: {elapsed:.2f}s',flush=True)
            expect(page.locator('#staging-badge')).to_be_visible()
            if snapshot['evidence']['mode']=='public_beta':
                expect(page.locator('#staging-badge')).to_contain_text('Бета-версия')
                expect(page.locator('#notice')).to_contain_text('Покрытие истории JURY неполное')
                expect(page.locator('#notice')).to_contain_text('История до')
                expect(page.locator('#available-history')).to_have_text('Доступная история')
            expect(page.locator('#audit-line')).to_contain_text('Сверка исходной истории')
            for i,n in enumerate(counts):
                raw=page.locator('#metrics .metric').nth(i).inner_text()
                assert int(''.join(raw.split()))==n,(i,raw,n)
            assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'),width
            page.locator('#language').click()
            expect(page.locator('#audit-line')).to_contain_text('Seed history audit')
            assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'),width
            if has_manifest and width==393:
                expect(page.locator('#audit-line')).to_contain_text('Current trace revisions')
                page.locator('[data-period="7d"]').click()
                page.locator('#filters button').nth(1).click()
                with page.expect_response('**/release.json'):
                    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                expect(page.locator('[data-period="7d"]')).to_have_attribute('aria-pressed','true')
                expect(page.locator('#filters button').nth(1)).to_have_attribute('aria-pressed','true')
                assert sum(url.endswith('/snapshot.json') for url in requests)==1
                page.context.set_offline(True)
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                expect(page.locator('#notice')).to_contain_text('Cached version')
                page.context.set_offline(False)
                page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                expect(page.locator('#notice')).not_to_contain_text('Cached version')
                if snapshot['evidence'].get('release'):
                    page.route('**/release.json',lambda route:route.fulfill(status=404))
                    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                    expect(page.locator('#notice')).to_contain_text('Cached version')
                    assert sum(url.endswith('/snapshot.json') for url in requests)==1
            assert not errors,errors
            page.close()
        browser.close()
finally:server.shutdown()
print(f'Actual persistent snapshot rendered at {widths} pixels in both languages')
