"""Integration test for web search — runs inside Docker with real Agent SDK.

Usage: npm run test:integration
"""

import asyncio
import sys

sys.path.insert(0, "/app/src")


def test_web_search_returns_results():
    """web_search should return a list of results with title/url/snippet."""
    from engine.api.chat import _web_search

    results = asyncio.run(_web_search("what is Python programming language", max_results=3))

    assert isinstance(results, list), f"Expected list, got {type(results)}"
    assert len(results) > 0, "Expected at least 1 result"

    # Should not be an error
    if len(results) == 1 and "error" in results[0]:
        raise AssertionError(f"Search returned error: {results[0]['error']}")

    for r in results:
        assert "title" in r or "url" in r, f"Result missing title/url: {r}"


def test_web_search_handles_empty_query():
    """Empty query should not crash."""
    from engine.api.chat import _web_search

    results = asyncio.run(_web_search(""))
    assert isinstance(results, list)


def test_web_search_result_format():
    """Results should have consistent structure."""
    from engine.api.chat import _web_search

    results = asyncio.run(_web_search("SearXNG meta search engine", max_results=2))

    if len(results) > 0 and "error" not in results[0]:
        for r in results:
            assert isinstance(r, dict), f"Result should be dict, got {type(r)}"
            # At minimum should have title or url
            has_content = any(k in r for k in ("title", "url", "snippet"))
            assert has_content, f"Result has no content fields: {r}"


if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        test_web_search_returns_results,
        test_web_search_handles_empty_query,
        test_web_search_result_format,
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
    sys.exit(1 if failed else 0)
