"""Unified LLM interface for Claude and Gemini.

Supports two Claude backends (configured via LLM_BACKEND env var):
  - "cli"  (default) — shells out to the Claude CLI binary.
                        Required for WebSearch/WebFetch tool calls.
  - "sdk"            — uses the anthropic Python SDK directly.
                        Faster startup, no CLI dependency, but no web tools.

If LLM_BACKEND=sdk is set but a call requests tools (WebSearch/WebFetch),
the call automatically falls back to the CLI backend for that request.

Gemini always uses its CLI.

Instructor integration (optional):
  When the `instructor` package is installed and the SDK backend is active,
  callers can use `run_instructor()` to get validated Pydantic model instances
  directly, with automatic retry on validation failure.

Prompt caching:
  `run_sdk_cached()` sends multi-part messages with cache_control on the
  context block, reducing input token costs for repeated taxonomy/context.
"""
import json
import logging
import os
import subprocess
import time

from json_repair import loads as repair_loads
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import (
    CLAUDE_BIN, CLAUDE_COMMON_FLAGS,
    GEMINI_BIN, GEMINI_COMMON_FLAGS,
)

logger = logging.getLogger(__name__)

# Optional imports — app works without these packages
try:
    import instructor as _instructor
    INSTRUCTOR_AVAILABLE = True
except ImportError:
    _instructor = None
    INSTRUCTOR_AVAILABLE = False

try:
    import anthropic as _anthropic
    ANTHROPIC_SDK_AVAILABLE = True
except ImportError:
    _anthropic = None
    ANTHROPIC_SDK_AVAILABLE = False

LLM_BACKEND = os.environ.get("LLM_BACKEND", "cli").lower()


def is_gemini_model(model: str) -> bool:
    """Check if a model string refers to a Gemini model."""
    return model.startswith("gemini")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((subprocess.TimeoutExpired, ConnectionError, OSError)),
)
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


# ---- Instructor (structured output with Pydantic validation) -----------------

def sdk_available() -> bool:
    """Return True if the Anthropic SDK path is usable (package + API key)."""
    return (ANTHROPIC_SDK_AVAILABLE
            and bool(os.environ.get("ANTHROPIC_API_KEY")))


def instructor_available() -> bool:
    """Return True if both Instructor and Anthropic SDK are usable."""
    return INSTRUCTOR_AVAILABLE and sdk_available()


def run_instructor(prompt, model, response_model, timeout=120,
                   max_retries=3, system=None, context=None):
    """Run an LLM call via Instructor, returning a validated Pydantic model.

    This function is SDK-only.  Callers must check instructor_available()
    first and fall back to the dict-based path when it returns False.

    Args:
        prompt: The user prompt text (or the specific question part).
        model: Claude model name.
        response_model: A Pydantic BaseModel class (e.g. CompanyResearch).
        timeout: Request timeout in seconds.
        max_retries: Instructor auto-retries on validation failure.
        system: Optional system message string.
        context: Optional context string to prepend as a cached content block.

    Returns:
        A tuple (model_instance, metadata_dict) where metadata_dict contains
        cost_usd, duration_ms, and model name.

    Raises:
        RuntimeError on API errors.
        ValidationError if retries are exhausted.
    """
    client = _instructor.from_anthropic(_anthropic.Anthropic())
    start = time.time()

    # Build messages with optional prompt caching
    if context:
        content = [
            {
                "type": "text",
                "text": context,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": prompt},
        ]
    else:
        content = prompt

    kwargs = {
        "model": model,
        "response_model": response_model,
        "max_retries": max_retries,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": content}],
    }
    if system:
        kwargs["system"] = system

    try:
        result = client.messages.create(**kwargs)
    except Exception as e:
        raise RuntimeError(f"Instructor/Anthropic error: {e}")

    elapsed_ms = int((time.time() - start) * 1000)

    # Instructor returns the Pydantic model directly; raw usage is on _raw_response
    cost_usd = 0.0
    raw_resp = getattr(result, "_raw_response", None)
    if raw_resp and hasattr(raw_resp, "usage") and raw_resp.usage:
        input_tokens = raw_resp.usage.input_tokens
        output_tokens = raw_resp.usage.output_tokens
        if "haiku" in model:
            cost_usd = (input_tokens * 0.80 + output_tokens * 4.0) / 1_000_000
        elif "sonnet" in model:
            cost_usd = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000
        elif "opus" in model:
            cost_usd = (input_tokens * 15.0 + output_tokens * 75.0) / 1_000_000

    meta = {
        "cost_usd": round(cost_usd, 4),
        "duration_ms": elapsed_ms,
        "model": model,
    }

    return result, meta


# ---- SDK with prompt caching -------------------------------------------------

def run_sdk_cached(prompt, model, timeout, json_schema=None,
                   context=None, system=None):
    """Call Claude SDK with prompt caching on the context block.

    Identical to _run_claude_sdk but splits the user message into a
    cached context block + a question block when *context* is provided.
    Falls back to run_cli (no caching) if the SDK is unavailable.

    Args:
        prompt: The specific question / instruction text.
        model: Claude model name.
        timeout: Timeout in seconds.
        json_schema: Optional JSON schema string for structured output.
        context: Large context text to cache (taxonomy tree, company list, etc.).
        system: Optional system message string.

    Returns:
        Standard normalised response dict (same as run_cli).
    """
    if not sdk_available():
        # Fall back to regular run_cli (no caching)
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        return run_cli(full_prompt, model, timeout, json_schema=json_schema)

    import anthropic
    client = anthropic.Anthropic()
    start = time.time()

    # Build user content with cache_control on context block
    if context:
        user_content = [
            {
                "type": "text",
                "text": context,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": prompt},
        ]
    else:
        user_content = prompt

    kwargs = {
        "model": model,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": user_content}],
    }

    if system:
        kwargs["system"] = system

    if json_schema:
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
        raise subprocess.TimeoutExpired(cmd="anthropic-sdk-cached", timeout=timeout)
    except anthropic.APIError as e:
        raise RuntimeError(f"Anthropic API error: {e}")

    elapsed_ms = int((time.time() - start) * 1000)

    text_parts = []
    structured_output = None
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            structured_output = block.input

    cost_usd = 0.0
    if response.usage:
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        # Check for cache-related usage fields
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        if "haiku" in model:
            cost_usd = (input_tokens * 0.80 + output_tokens * 4.0) / 1_000_000
        elif "sonnet" in model:
            cost_usd = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000
        elif "opus" in model:
            cost_usd = (input_tokens * 15.0 + output_tokens * 75.0) / 1_000_000
        # Log cache stats for observability
        if cache_read or cache_creation:
            logger.info(
                "Prompt cache: %d tokens read, %d tokens created (model=%s)",
                cache_read, cache_creation, model,
            )

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

    response = repair_loads(result.stdout)
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

    raw = repair_loads(result.stdout)

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
