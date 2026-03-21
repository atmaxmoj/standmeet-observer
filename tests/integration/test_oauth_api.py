"""Test OAuth token with direct Anthropic API — minimal reproduction."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app/src")

RESULTS_DIR = Path("/data/test_results")


def save_result(name, data):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"oauth_{name}.json").write_text(
        json.dumps(data, indent=2, default=str))


def test_oauth_simple_message():
    """Simplest possible OAuth API call — no tools."""
    import anthropic

    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not token:
        print("  SKIP  no CLAUDE_CODE_OAUTH_TOKEN")
        return

    client = anthropic.Anthropic(
        api_key=None,
        auth_token=token,
        default_headers={
            "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
            "user-agent": "claude-cli/2.1.75",
            "x-app": "cli",
        },
    )

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": "Say hello in one word."}],
        )
        save_result("simple", {"text": resp.content[0].text, "usage": dict(resp.usage)})
        print(f"  Response: {resp.content[0].text}")
    except Exception as e:
        save_result("simple_error", {"error": str(e), "type": type(e).__name__})
        raise


def test_oauth_with_tools():
    """OAuth API call WITH tools."""
    import anthropic

    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not token:
        print("  SKIP  no CLAUDE_CODE_OAUTH_TOKEN")
        return

    client = anthropic.Anthropic(
        api_key=None,
        auth_token=token,
        default_headers={
            "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
            "user-agent": "claude-cli/2.1.75",
            "x-app": "cli",
        },
    )

    tools = [
        {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    ]

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
            tools=tools,
        )
        content = [{"type": b.type, "text": getattr(b, "text", None),
                     "name": getattr(b, "name", None), "input": getattr(b, "input", None)}
                    for b in resp.content]
        save_result("tools", {"content": content, "stop_reason": resp.stop_reason,
                              "usage": dict(resp.usage)})
        print(f"  Stop reason: {resp.stop_reason}")
        print(f"  Content: {content}")
    except Exception as e:
        save_result("tools_error", {"error": str(e), "type": type(e).__name__})
        raise


def test_oauth_opus_with_tools():
    """Test Opus model with OAuth + tools via AgentService."""
    from engine.infrastructure.llm.types import DirectAPIClient, ToolDef
    from engine.infrastructure.agent.service import AgentService

    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not token:
        print("  SKIP  no CLAUDE_CODE_OAUTH_TOKEN")
        return

    client = DirectAPIClient(auth_token=token)
    agent = AgentService(client)

    tool_called = {}

    def get_weather(city: str) -> dict:
        tool_called["city"] = city
        return {"city": city, "temp": "20°C", "condition": "sunny"}

    tools = [
        ToolDef(
            name="get_weather",
            description="Get current weather.",
            input_schema={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
            handler=get_weather,
        ),
    ]

    try:
        resp = agent.complete_with_tools(
            "What's the weather in Tokyo? Use the get_weather tool.",
            "claude-opus-4-6",
            tools,
            max_turns=3,
        )
        save_result("opus_tools", {
            "text": resp.text[:500],
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "tool_called": tool_called,
        })
        print(f"  Opus response: {resp.text[:100]}")
        print(f"  Tool called: {tool_called}")
    except Exception as e:
        save_result("opus_tools_error", {"error": str(e), "type": type(e).__name__})
        raise


if __name__ == "__main__":
    passed = 0
    failed = 0
    for test in [test_oauth_simple_message, test_oauth_with_tools, test_oauth_opus_with_tools]:
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
