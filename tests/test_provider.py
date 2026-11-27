import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from provider import tonapi_request


class ProviderTests(unittest.TestCase):
    @patch('provider.time.sleep')
    @patch('provider.urllib.request.urlopen')
    def test_not_found_is_not_retried(self, open_url, sleep):
        open_url.side_effect = HTTPError('', 404, 'not found', {}, None)
        with self.assertRaises(HTTPError):
            tonapi_request('events/example', {})
        self.assertEqual(open_url.call_count, 1)
        sleep.assert_not_called()

    @patch('provider.time.sleep')
    @patch('provider.urllib.request.urlopen')
    def test_transient_http_response_respects_retry_after(self, open_url, sleep):
        open_url.side_effect = [
            HTTPError('', 429, 'rate limit', {'Retry-After': '8'}, None),
            io.BytesIO(b'{"actions": []}'),
        ]
        self.assertEqual(tonapi_request('events/example', {}), {'actions': []})
        self.assertGreaterEqual(sleep.call_args_list[0].args[0], 8)

    @patch('provider.urllib.request.urlopen')
    def test_expired_deadline_makes_no_request(self, open_url):
        with self.assertRaises(TimeoutError):
            tonapi_request('events/example', {}, deadline=0)
        open_url.assert_not_called()
