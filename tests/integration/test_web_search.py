"""Integration test for web search — runs inside Docker with real Agent SDK.

Verifies that web search ACTUALLY searches (not just LLM hallucination).
Results + traces written to /data/test_results/ for inspection.

Usage: npm run test:integration
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app/src")

RESULTS_DIR = Path("/data/test_results")


def save_result(name: str, data: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"web_search_{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def test_web_search_returns_results():
    """web_search should return a non-empty list of results."""
    from engine.application.chat import web_search as _web_search

    results = asyncio.run(_web_search("what is Python programming language", max_results=3))
    save_result("basic", {"query": "what is Python programming language", "results": results})

    assert isinstance(results, list), f"Expected list, got {type(results)}"
    assert len(results) > 0, "Expected at least 1 result"

    if len(results) == 1 and "error" in results[0]:
        raise AssertionError(f"Search returned error: {results[0]}")


def test_web_search_recent_content():
    """Search for something that CAN'T be in training data — today's date.

    If results mention today's date or very recent events, it actually searched.
    """
    from engine.application.chat import web_search as _web_search

    today = datetime.now().strftime("%Y-%m-%d")
    query = f"news today {today}"
    results = asyncio.run(_web_search(query, max_results=3))
    save_result("recent", {"query": query, "date": today, "results": results})

    assert isinstance(results, list)
    assert len(results) > 0

    # At least one result should have a URL (real search results have URLs)
    has_url = any(r.get("url") for r in results if isinstance(r, dict) and "error" not in r)
    assert has_url, f"No results with URLs — likely hallucinated. Results: {results}"


def test_web_search_url_validity():
    """Returned URLs should look like real URLs (http/https)."""
    from engine.application.chat import web_search as _web_search

    results = asyncio.run(_web_search("SearXNG meta search engine github", max_results=3))
    save_result("urls", {"query": "SearXNG meta search engine github", "results": results})

    assert isinstance(results, list)
    urls = [r.get("url", "") for r in results if isinstance(r, dict)]
    real_urls = [u for u in urls if u.startswith("http")]
    assert len(real_urls) > 0, f"No real URLs found. URLs: {urls}"


def test_web_search_handles_empty_query():
    """Empty query should not crash."""
    from engine.application.chat import web_search as _web_search

    results = asyncio.run(_web_search(""))
    save_result("empty", {"query": "", "results": results})
    assert isinstance(results, list)


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_web_search_returns_results,
        test_web_search_recent_content,
        test_web_search_url_validity,
        test_web_search_handles_empty_query,
    ]
    for test in tests:
        name = test.__name__
        try:
            test()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    print(f"Results saved to {RESULTS_DIR}/")
    sys.exit(1 if failed else 0)
