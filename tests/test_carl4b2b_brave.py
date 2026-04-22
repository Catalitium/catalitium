"""Unit tests for the Carl4B2B Brave Search integration.

All network calls are mocked. These tests never hit the real Brave API.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from app.controllers import carl4b2b_brave as brave


class TestBuildQuery(unittest.TestCase):
    def test_company_requires_company_name(self) -> None:
        self.assertEqual(brave.build_query("company", {"company": ""}), "")

    def test_company_happy_path(self) -> None:
        q = brave.build_query("company", {"company": "OpenAI"})
        self.assertIn('"OpenAI"', q)
        self.assertIn("hiring news", q)

    def test_role_market_with_title_and_country(self) -> None:
        q = brave.build_query(
            "role_market",
            {"title": "Data Analyst", "country": "UK"},
        )
        self.assertIn('"Data Analyst"', q)
        self.assertIn("hiring market", q)
        self.assertIn("UK", q)

    def test_role_market_tolerates_missing_country(self) -> None:
        q = brave.build_query("role_market", {"title": "Product Manager"})
        self.assertIn('"Product Manager"', q)
        self.assertIn("hiring market", q)

    def test_competitor_requires_top_hirers(self) -> None:
        self.assertEqual(brave.build_query("competitor", {}), "")
        self.assertEqual(brave.build_query("competitor", {"top_hirers": []}), "")

    def test_competitor_caps_at_three(self) -> None:
        q = brave.build_query(
            "competitor",
            {"top_hirers": ["A", "B", "C", "D", "E"]},
        )
        self.assertIn('"A"', q)
        self.assertIn('"B"', q)
        self.assertIn('"C"', q)
        self.assertNotIn('"D"', q)
        self.assertIn(" OR ", q)

    def test_unknown_context_type_returns_empty(self) -> None:
        self.assertEqual(brave.build_query("anything_else", {"company": "X"}), "")

    def test_whitespace_normalized(self) -> None:
        q = brave.build_query("company", {"company": "  Open   AI  "})
        self.assertIn('"Open AI"', q)


class TestFetchBraveContext(unittest.TestCase):
    def setUp(self) -> None:
        brave.BRAVE_CACHE._store.clear()

    def test_missing_api_key_returns_none(self) -> None:
        with mock.patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": ""}, clear=False):
            self.assertIsNone(brave.fetch_brave_context("test query", api_key=""))

    def test_empty_query_returns_none(self) -> None:
        self.assertIsNone(brave.fetch_brave_context("   ", api_key="k"))
        self.assertIsNone(brave.fetch_brave_context("", api_key="k"))

    def _make_response(self, payload: dict, status: int = 200) -> mock.MagicMock:
        resp = mock.MagicMock()
        resp.status = status
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__ = mock.MagicMock(return_value=resp)
        resp.__exit__ = mock.MagicMock(return_value=False)
        return resp

    def test_happy_path_parses_and_caches(self) -> None:
        payload = {
            "web": {
                "results": [
                    {
                        "title": "OpenAI is hiring data analysts",
                        "url": "https://example.com/openai-hiring",
                        "description": "The company posted several new roles...",
                        "age": "2 days ago",
                    }
                ]
            }
        }
        resp = self._make_response(payload, status=200)
        with mock.patch.object(brave, "urlopen", return_value=resp) as mocked:
            out = brave.fetch_brave_context("OpenAI hiring", api_key="testkey")
            self.assertIsInstance(out, list)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["url"], "https://example.com/openai-hiring")
            self.assertEqual(mocked.call_count, 1)

            out2 = brave.fetch_brave_context("OpenAI hiring", api_key="testkey")
            self.assertEqual(out2, out)
            self.assertEqual(mocked.call_count, 1, "second call must be served from cache")

    def test_http_error_returns_none(self) -> None:
        from urllib.error import HTTPError

        err = HTTPError(
            url=brave.BRAVE_API_ENDPOINT,
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )
        with mock.patch.object(brave, "urlopen", side_effect=err):
            self.assertIsNone(brave.fetch_brave_context("q", api_key="k"))
        self.assertIsNone(brave.BRAVE_CACHE.get(brave._cache_key("q")))

    def test_url_error_returns_none(self) -> None:
        from urllib.error import URLError

        with mock.patch.object(brave, "urlopen", side_effect=URLError("timeout")):
            self.assertIsNone(brave.fetch_brave_context("q", api_key="k"))

    def test_unexpected_exception_returns_none(self) -> None:
        with mock.patch.object(brave, "urlopen", side_effect=RuntimeError("boom")):
            self.assertIsNone(brave.fetch_brave_context("q", api_key="k"))

    def test_non_200_status_returns_none(self) -> None:
        resp = self._make_response({}, status=500)
        with mock.patch.object(brave, "urlopen", return_value=resp):
            self.assertIsNone(brave.fetch_brave_context("q", api_key="k"))

    def test_malformed_json_returns_none(self) -> None:
        resp = mock.MagicMock()
        resp.status = 200
        resp.read.return_value = b"not-json-at-all"
        resp.__enter__ = mock.MagicMock(return_value=resp)
        resp.__exit__ = mock.MagicMock(return_value=False)
        with mock.patch.object(brave, "urlopen", return_value=resp):
            self.assertIsNone(brave.fetch_brave_context("q", api_key="k"))

    def test_empty_results_list_cached_as_empty(self) -> None:
        resp = self._make_response({"web": {"results": []}})
        with mock.patch.object(brave, "urlopen", return_value=resp):
            out = brave.fetch_brave_context("quiet query", api_key="k")
            self.assertEqual(out, [])

    def test_parser_skips_items_without_url_or_title(self) -> None:
        payload = {
            "web": {
                "results": [
                    {"title": "no url", "url": ""},
                    {"title": "", "url": "https://x"},
                    {"title": "ok", "url": "https://good.example"},
                    {"title": "bad scheme", "url": "javascript:alert(1)"},
                ]
            }
        }
        resp = self._make_response(payload)
        with mock.patch.object(brave, "urlopen", return_value=resp):
            out = brave.fetch_brave_context("mixed", api_key="k")
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["url"], "https://good.example")

    def test_truncates_long_descriptions(self) -> None:
        long_desc = "x" * 5000
        payload = {
            "web": {
                "results": [
                    {
                        "title": "t",
                        "url": "https://example.com",
                        "description": long_desc,
                    }
                ]
            }
        }
        resp = self._make_response(payload)
        with mock.patch.object(brave, "urlopen", return_value=resp):
            out = brave.fetch_brave_context("long", api_key="k")
            self.assertLessEqual(len(out[0]["description"]), brave.BRAVE_SNIPPET_MAX_CHARS)

    def test_caps_results_at_brave_result_max(self) -> None:
        items = [
            {"title": f"r{i}", "url": f"https://example.com/{i}"}
            for i in range(50)
        ]
        resp = self._make_response({"web": {"results": items}})
        with mock.patch.object(brave, "urlopen", return_value=resp):
            out = brave.fetch_brave_context("many", api_key="k")
            self.assertLessEqual(len(out), brave.BRAVE_RESULT_MAX)


if __name__ == "__main__":
    unittest.main()
