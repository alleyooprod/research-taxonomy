"""Unified LLM interface for Claude and Gemini.

Supports two Claude backends (configured via LLM_BACKEND env var):
  - "cli"  (default) — shells out to the Claude CLI binary.
                        Required for WebSearch/WebFetch tool calls.
  - "sdk"            — uses the anthropic Python SDK directly.
                        Faster startup, no CLI dependency, but no web tools.

If LLM_BACKEND=sdk is set but a call requests tools (WebSearch/WebFetch),
the call automatically falls back to the CLI backend for that request.

Gemini always uses its CLI.
"""
import json
import logging
import os
import subprocess
import time

from config import (
    CLAUDE_BIN, CLAUDE_COMMON_FLAGS,
    GEMINI_BIN, GEMINI_COMMON_FLAGS,
)

logger = logging.getLogger(__name__)

LLM_BACKEND = os.environ.get("LLM_BACKEND", "cli").lower()


def is_gemini_model(model: str) -> bool:
    """Check if a model string refers to a Gemini model."""
    return model.startswith("gemini")


def run_cli(prompt: str, model: str, timeout: int,
            tools: str = None, json_schema: str = None) -> dict:
    """Run an LLM call and return a normalised response dict.

    Args:
        prompt: The prompt text.
        model: Full model name (e.g. "claude-opus-4-6" or "gemini-2.0-flash").
        timeout: Hard timeout in seconds.
        tools: Comma-separated tool names (Claude: "WebSearch,WebFetch").
               Ignored for Gemini (has built-in Google Search grounding).
        json_schema: JSON schema string for structured output (Claude only).

    Returns:
        Dict matching Claude CLI JSON format:
          result (str), cost_usd (float), duration_ms (int),
          structured_output (dict|None), is_error (bool).

    Raises:
        subprocess.TimeoutExpired: CLI call exceeded *timeout*.
        RuntimeError: CLI returned a non-zero exit code or flagged an error.
    """
    if is_gemini_model(model):
        return _run_gemini(prompt, model, timeout)

    # Use SDK for Claude when possible, fall back to CLI for web tools
    needs_cli_tools = tools and any(t.strip() for t in tools.split(","))
    if LLM_BACKEND == "sdk" and not needs_cli_tools:
        return _run_claude_sdk(prompt, model, timeout, json_schema)

    try:
        return _run_claude_cli(prompt, model, timeout, tools, json_schema)
    except FileNotFoundError:
        logger.warning("Claude CLI binary not found, attempting SDK fallback")
        if not needs_cli_tools:
            return _run_claude_sdk(prompt, model, timeout, json_schema)
        raise RuntimeError(
            "Claude CLI not found. Install it (run 'claude' in terminal) "
            "or set an Anthropic API key in Settings to use SDK mode."
        )


# ---- Claude SDK -------------------------------------------------------------

def _run_claude_sdk(prompt, model, timeout, json_schema=None):
    """Call Claude via the Anthropic Python SDK."""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed, falling back to CLI")
        return _run_claude_cli(prompt, model, timeout, json_schema=json_schema)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set, falling back to CLI")
        return _run_claude_cli(prompt, model, timeout, json_schema=json_schema)

    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    start = time.time()

    kwargs = {
        "model": model,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
    }

    if json_schema:
        # Parse the schema string and use it as a tool for structured output
        schema_obj = json.loads(json_schema) if isinstance(json_schema, str) else json_schema
        tool_name = schema_obj.get("name", "structured_output")
        kwargs["tools"] = [{
            "name": tool_name,
            "description": "Return structured output matching the schema.",
            "input_schema": schema_obj.get("schema", schema_obj),
        }]
        kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

    try:
        response = client.messages.create(**kwargs)
    except anthropic.APITimeoutError:
        raise subprocess.TimeoutExpired(cmd="anthropic-sdk", timeout=timeout)
    except anthropic.APIError as e:
        raise RuntimeError(f"Anthropic API error: {e}")

    elapsed_ms = int((time.time() - start) * 1000)

    # Extract text and structured output
    text_parts = []
    structured_output = None
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            structured_output = block.input

    # Calculate cost from usage
    cost_usd = 0.0
    if response.usage:
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        if "haiku" in model:
            cost_usd = (input_tokens * 0.80 + output_tokens * 4.0) / 1_000_000
        elif "sonnet" in model:
            cost_usd = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000
        elif "opus" in model:
            cost_usd = (input_tokens * 15.0 + output_tokens * 75.0) / 1_000_000

    return {
        "result": "\n".join(text_parts),
        "cost_usd": round(cost_usd, 4),
        "duration_ms": elapsed_ms,
        "structured_output": structured_output,
        "is_error": False,
    }


# ---- Claude CLI --------------------------------------------------------------

def _run_claude_cli(prompt, model, timeout, tools=None, json_schema=None):
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        *CLAUDE_COMMON_FLAGS,
        "--model", model,
        "--no-session-persistence",
    ]
    if tools:
        cmd += ["--tools", tools]
    if json_schema:
        cmd += ["--json-schema", json_schema]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0:
        stderr = result.stderr.strip()[:500] if result.stderr else "unknown error"
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {stderr}")

    response = json.loads(result.stdout)
    if response.get("is_error"):
        raise RuntimeError(f"Claude error: {response.get('result', 'unknown')[:300]}")

    return response


# ---- Gemini -----------------------------------------------------------------

def _run_gemini(prompt, model, timeout):
    cmd = [
        *GEMINI_BIN,
        "-p", prompt,
        *GEMINI_COMMON_FLAGS,
        "--model", model,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError(
            "Gemini CLI (npx) not found. Install Node.js from https://nodejs.org "
            "then run 'npx @google/gemini-cli' once to set up, or switch to a Claude model."
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()[:500] if result.stderr else "unknown error"
        raise RuntimeError(f"Gemini CLI failed (exit {result.returncode}): {stderr}")

    raw = json.loads(result.stdout)

    # Normalise Gemini response to Claude-like format.
    text = raw.get("response") or raw.get("result") or ""

    # Fallback: extract from turns if top-level text is empty
    if not text and "turns" in raw:
        for turn in reversed(raw.get("turns", [])):
            if turn.get("role") == "model":
                parts = turn.get("parts", [])
                text = " ".join(p.get("text", "") for p in parts if "text" in p)
                if text:
                    break

    return {
        "result": text,
        "cost_usd": 0,
        "duration_ms": 0,
        "structured_output": None,
        "is_error": False,
    }
