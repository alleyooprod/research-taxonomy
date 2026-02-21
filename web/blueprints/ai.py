"""AI features API: discover, find-similar, chat, market reports.

Uses Instructor + Pydantic validation + prompt caching on the SDK path
for chat (which has no web tool dependency).  Other endpoints that need
web tools (discover, find-similar, pricing, reports) continue using CLI
with optional Pydantic post-validation.
"""
import json
import logging
import os
import re
import shutil
import subprocess

from flask import Blueprint, current_app, jsonify, request

from config import (
    DATA_DIR, DEFAULT_MODEL, MODEL_CHOICES, CLAUDE_BIN, RESEARCH_MODEL,
    load_app_settings, save_app_settings,
    save_api_key as save_api_key_to_keychain,
)
from core.git_sync import sync_to_git_async
from core.llm import (
    run_cli, is_gemini_model, LLM_BACKEND,
    instructor_available, run_instructor, run_sdk_cached,
)
from storage.db import Database
from web.async_jobs import start_async_job, write_result, poll_result

logger = logging.getLogger(__name__)

# Optional: Pydantic models for structured validation
try:
    from core.models import (
        ChatResponse, PricingResearch, DiscoverResult,
        DiscoveredCompany, PYDANTIC_AVAILABLE,
    )
except ImportError:
    ChatResponse = None
    PricingResearch = None
    DiscoverResult = None
    DiscoveredCompany = None
    PYDANTIC_AVAILABLE = False

ai_bp = Blueprint("ai", __name__)

_VALID_MODELS = set(MODEL_CHOICES.values())


def _validate_model(model):
    """Return model if valid, else None (caller uses its default)."""
    if model and model in _VALID_MODELS:
        return model
    return None


def _sanitize_for_prompt(text, max_length=500):
    """Sanitize user input before interpolating into AI prompts.
    Strips control chars, prompt injection markers, and truncates."""
    if not text:
        return ""
    # Strip non-printable/control characters
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    sanitized = sanitized.replace("```", "").replace("---", "")
    # Case-insensitive removal of prompt injection markers
    injection_patterns = [
        r'(?i)\bsystem\s*:', r'(?i)\bassistant\s*:', r'(?i)\bhuman\s*:',
        r'(?i)\buser\s*:', r'(?i)\binstruction\s*:',
        r'(?i)ignore\s+(previous|above|all)', r'(?i)disregard',
        r'(?i)forget\s+(everything|previous|all|above)',
        r'(?i)you\s+are\s+now', r'(?i)new\s+instructions?\s*:',
        r'(?i)override\s+(previous|all|system)',
    ]
    for pattern in injection_patterns:
        sanitized = re.sub(pattern, '', sanitized)
    sanitized = re.sub(r'\n{3,}', '\n\n', sanitized)
    return sanitized[:max_length].strip()


# --- Models ---

@ai_bp.route("/api/ai/models")
def ai_models():
    return jsonify({
        "models": MODEL_CHOICES,
        "providers": {
            "claude": {
                "models": {k: v for k, v in MODEL_CHOICES.items()
                           if not v.startswith("gemini")},
                "label": "Claude (Anthropic)",
            },
            "gemini": {
                "models": {k: v for k, v in MODEL_CHOICES.items()
                           if v.startswith("gemini")},
                "label": "Gemini (Google)",
            },
        },
    })


# --- AI Setup & Status ---

@ai_bp.route("/api/ai/setup-status")
def ai_setup_status():
    """Return status of all AI backends for the setup panel."""
    settings = load_app_settings()
    api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.get("anthropic_api_key", "")

    claude_cli_path = shutil.which("claude")
    node_path = shutil.which("node")
    npx_path = shutil.which("npx")

    # Mask API key for display
    api_key_masked = ""
    if api_key:
        api_key_masked = f"sk-ant-...{api_key[-4:]}" if len(api_key) > 12 else "***"

    return jsonify({
        "claude_cli": {
            "installed": claude_cli_path is not None,
            "path": claude_cli_path or "",
        },
        "claude_sdk": {
            "api_key_set": bool(api_key),
            "api_key_masked": api_key_masked,
            "backend": LLM_BACKEND,
        },
        "gemini": {
            "node_installed": node_path is not None,
            "npx_installed": npx_path is not None,
            "node_path": node_path or "",
        },
    })


@ai_bp.route("/api/ai/save-api-key", methods=["POST"])
def ai_save_api_key():
    """Save Anthropic API key from the setup panel."""
    data = request.json
    api_key = data.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "API key is required"}), 400
    if not api_key.startswith("sk-ant-"):
        return jsonify({"error": "Invalid key format. Anthropic keys start with sk-ant-"}), 400

    save_api_key_to_keychain(api_key)

    # Also set in environment for the current process
    os.environ["ANTHROPIC_API_KEY"] = api_key

    masked = f"sk-ant-...{api_key[-4:]}" if len(api_key) > 12 else "***"
    return jsonify({"ok": True, "masked": masked})


@ai_bp.route("/api/ai/test-backend", methods=["POST"])
def ai_test_backend():
    """Test an AI backend with a minimal prompt."""
    data = request.json
    backend = data.get("backend", "claude_cli")  # claude_cli, claude_sdk, gemini

    try:
        if backend == "claude_sdk":
            settings = load_app_settings()
            api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.get("anthropic_api_key", "")
            if not api_key:
                return jsonify({"ok": False, "error": "No API key configured"})

            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "Reply with just the word OK"}],
            )
            return jsonify({"ok": True, "message": "Claude SDK connected successfully"})

        elif backend == "claude_cli":
            claude_path = shutil.which("claude")
            if not claude_path:
                return jsonify({"ok": False, "error": "Claude CLI not found in PATH"})
            result = subprocess.run(
                [CLAUDE_BIN, "-p", "Reply with just the word OK",
                 "--output-format", "json", "--model", "claude-haiku-4-5-20251001",
                 "--no-session-persistence"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()[:300] if result.stderr else "Unknown error"
                return jsonify({"ok": False, "error": stderr})
            return jsonify({"ok": True, "message": "Claude CLI working"})

        elif backend == "gemini":
            if not shutil.which("npx"):
                return jsonify({"ok": False, "error": "npx not found. Install Node.js first."})
            result = subprocess.run(
                ["npx", "@google/gemini-cli", "-p",
                 "Reply with just the word OK",
                 "--output-format", "json", "-y",
                 "--model", "gemini-2.0-flash"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()[:300] if result.stderr else "Unknown error"
                return jsonify({"ok": False, "error": stderr})
            return jsonify({"ok": True, "message": "Gemini CLI working"})

        return jsonify({"ok": False, "error": f"Unknown backend: {backend}"})

    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Test timed out after 30 seconds"})
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": f"Binary not found: {e}"})
    except Exception as e:
        logger.error("Backend test failed (%s): %s", backend, e)
        return jsonify({"ok": False, "error": "An internal error occurred. Check logs for details."})


# --- Default Model ---

@ai_bp.route("/api/ai/default-model")
def get_default_model():
    settings = load_app_settings()
    return jsonify({"model": settings.get("default_model", DEFAULT_MODEL)})


@ai_bp.route("/api/ai/default-model", methods=["POST"])
def set_default_model():
    data = request.json
    model = _validate_model(data.get("model")) or DEFAULT_MODEL
    settings = load_app_settings()
    settings["default_model"] = model
    save_app_settings(settings)
    return jsonify({"ok": True})


# --- Discover ---

def _run_discover(job_id, query, model):
    safe_query = _sanitize_for_prompt(query)
    prompt = f"""You are a market research assistant. The user is looking for companies in this space:

"{safe_query}"

Search the web and return a JSON array of 5-10 company objects, each with:
- "name": company name
- "url": company website URL (must be real, working URLs)
- "description": 1-sentence description of what they do

Only return the JSON array, nothing else. Focus on real, existing companies."""

    try:
        response = run_cli(prompt, model, timeout=120, tools="WebSearch,WebFetch")
        text = response.get("result", "")
        if not text or not text.strip():
            result = {"status": "error",
                      "error": "AI returned an empty response. Check your API key and model settings."}
        else:
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                companies = json.loads(match.group())
                result = {"status": "complete", "companies": companies}
            else:
                # Return error with the raw text so the user knows what happened
                logger.warning("Discovery JSON extraction failed for query %r. Raw: %s",
                               query, text[:500])
                result = {"status": "error",
                          "error": "AI response did not contain valid JSON. "
                                   "The model may need a different prompt or the query was too vague.",
                          "raw": text[:1000]}
    except subprocess.TimeoutExpired:
        result = {"status": "error", "error": "Discovery timed out. Try a simpler query."}
    except json.JSONDecodeError as e:
        logger.error("Discovery JSON parse error for query %r: %s", query, e)
        result = {"status": "error", "error": "Failed to parse AI response as JSON."}
    except FileNotFoundError:
        result = {"status": "error",
                  "error": "Claude CLI not found. Install it or configure an API key in Settings."}
    except Exception as e:
        logger.error("Discovery failed for query %r: %s", query, e)
        result = {"status": "error", "error": f"Discovery failed: {str(e)[:200]}"}

    write_result("discover", job_id, result)


def _check_cli_available(model):
    """Return an error message if the model's CLI tool is not found, or None."""
    if is_gemini_model(model):
        if not shutil.which("npx"):
            return ("Gemini requires Node.js (npx). Install Node.js from "
                    "https://nodejs.org or switch to a Claude model.")
        return None

    # Claude model — check if SDK or CLI is available
    settings = load_app_settings()
    api_key = os.environ.get("ANTHROPIC_API_KEY") or settings.get("anthropic_api_key", "")
    if api_key:
        return None  # SDK fallback available
    if shutil.which("claude"):
        return None
    return ("Claude CLI not found and no API key configured. "
            "Either install the Claude CLI (run 'claude' in terminal) "
            "or set an Anthropic API key in Settings.")


@ai_bp.route("/api/ai/discover", methods=["POST"])
def ai_discover():
    data = request.json
    query = data.get("query", "").strip()
    model = _validate_model(data.get("model")) or DEFAULT_MODEL
    if not query:
        return jsonify({"error": "Query is required"}), 400

    # Pre-flight: check if the required CLI tool is available
    error = _check_cli_available(model)
    if error:
        return jsonify({"error": error}), 400

    discover_id = start_async_job("discover", _run_discover, query, model)
    return jsonify({"discover_id": discover_id})


@ai_bp.route("/api/ai/discover/<discover_id>")
def get_discover_status(discover_id):
    return jsonify(poll_result("discover", discover_id))


# --- Batch Pricing Research ---

def _run_pricing_research(job_id, project_id, company_ids, model):
    """Batch pricing research with optional Pydantic validation.

    Uses CLI with web tools (pricing needs web access).
    Validates results through PricingResearch model when available.
    """
    from pathlib import Path
    pricing_db = Database()
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "research_pricing.txt"
    prompt_template = prompt_path.read_text() if prompt_path.exists() else ""

    results = []
    for cid in company_ids:
        company = pricing_db.get_company(cid)
        if not company:
            continue
        prompt = prompt_template.format(name=company["name"], url=company["url"])
        try:
            response = run_cli(prompt, model, timeout=90,
                               tools="WebSearch,WebFetch",
                               json_schema=str(Path(__file__).parent.parent.parent / "prompts" / "schemas" / "pricing_research.json"))
            text = response.get("result", "")
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                pricing = json.loads(match.group())

                # Validate through Pydantic when available
                if PYDANTIC_AVAILABLE and PricingResearch is not None:
                    try:
                        validated = PricingResearch.model_validate(pricing)
                        pricing = validated.model_dump(exclude_none=True)
                    except Exception as e:
                        logger.debug("Pydantic pricing validation failed for %s: %s",
                                     company["name"], e)

                update = {}
                for pf in ("pricing_model", "pricing_b2c_low", "pricing_b2c_high",
                           "pricing_b2b_low", "pricing_b2b_high", "has_free_tier",
                           "revenue_model", "pricing_tiers", "pricing_notes"):
                    if pricing.get(pf) is not None:
                        val = pricing[pf]
                        if pf == "pricing_tiers" and not isinstance(val, str):
                            val = json.dumps(val)
                        update[pf] = val
                if update:
                    pricing_db.update_company(cid, update)
                results.append({"id": cid, "name": company["name"], "ok": True,
                                "fields": list(update.keys())})
            else:
                results.append({"id": cid, "name": company["name"], "ok": False,
                                "error": "No pricing data found"})
        except Exception as e:
            logger.error("Pricing research failed for company %s (id=%s): %s",
                         company["name"], cid, e)
            results.append({"id": cid, "name": company["name"], "ok": False,
                            "error": "An internal error occurred. Check logs for details."})

    write_result("pricing", job_id, {"status": "complete", "results": results})


@ai_bp.route("/api/ai/research-pricing", methods=["POST"])
def ai_research_pricing():
    db = current_app.db
    data = request.json
    project_id = data.get("project_id")
    model = _validate_model(data.get("model")) or DEFAULT_MODEL
    company_ids = data.get("company_ids")

    if not company_ids:
        companies = db.get_companies(project_id=project_id, limit=500)
        company_ids = [c["id"] for c in companies if not c.get("pricing_model")]
    if not company_ids:
        return jsonify({"error": "No companies need pricing research"}), 400

    error = _check_cli_available(model)
    if error:
        return jsonify({"error": error}), 400

    pricing_id = start_async_job("pricing", _run_pricing_research,
                                  project_id, company_ids, model)
    return jsonify({"pricing_id": pricing_id, "count": len(company_ids)})


@ai_bp.route("/api/ai/research-pricing/<pricing_id>")
def get_pricing_status(pricing_id):
    return jsonify(poll_result("pricing", pricing_id))


# --- Find Similar ---

def _run_find_similar(job_id, company, model):
    safe_name = _sanitize_for_prompt(company['name'], 100)
    safe_what = _sanitize_for_prompt(company.get('what', 'N/A'), 200)
    safe_target = _sanitize_for_prompt(company.get('target', 'N/A'), 200)

    prompt = f"""You are a market research assistant. Given this company:

Name: {safe_name}
URL: {company['url']}
What they do: {safe_what}
Target: {safe_target}
Category: {company.get('category_name', 'N/A')}

Search the web and find 5 similar or competing companies. Return a JSON array with:
- "name": company name
- "url": company website URL
- "description": 1-sentence description
- "similarity": brief explanation of why it's similar

Only return the JSON array, nothing else."""

    try:
        response = run_cli(prompt, model, timeout=120)
        text = response.get("result", "")
        if not text or not text.strip():
            result = {"status": "error",
                      "error": "AI returned an empty response. Check your API key and model settings."}
        else:
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                companies = json.loads(match.group())
                result = {"status": "complete", "companies": companies}
            else:
                logger.warning("Find-similar JSON extraction failed for %s. Raw: %s",
                               company.get('name', '?'), text[:500])
                result = {"status": "error",
                          "error": "AI response did not contain valid JSON.",
                          "raw": text[:1000]}
    except subprocess.TimeoutExpired:
        result = {"status": "error", "error": "Search timed out. Please try again."}
    except json.JSONDecodeError as e:
        logger.error("Find-similar JSON parse error for %s: %s", company.get('name', '?'), e)
        result = {"status": "error", "error": "Failed to parse AI response as JSON."}
    except FileNotFoundError:
        result = {"status": "error",
                  "error": "Claude CLI not found. Install it or configure an API key in Settings."}
    except Exception as e:
        logger.error("Find-similar failed for %s: %s", company.get('name', '?'), e)
        result = {"status": "error", "error": f"Find-similar failed: {str(e)[:200]}"}

    write_result("similar", job_id, result)


@ai_bp.route("/api/ai/find-similar", methods=["POST"])
def ai_find_similar():
    db = current_app.db
    data = request.json
    company_id = data.get("company_id")
    model = _validate_model(data.get("model")) or DEFAULT_MODEL
    if not company_id:
        return jsonify({"error": "company_id is required"}), 400

    company = db.get_company(company_id)
    if not company:
        return jsonify({"error": "Company not found"}), 404

    similar_id = start_async_job("similar", _run_find_similar, company, model)
    return jsonify({"similar_id": similar_id})


@ai_bp.route("/api/ai/find-similar/<similar_id>")
def get_similar_status(similar_id):
    return jsonify(poll_result("similar", similar_id))


# --- Chat ---

@ai_bp.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    """AI chat with taxonomy data.

    Strategy:
      1. Instructor + prompt caching on taxonomy context (if available).
      2. SDK with prompt caching (if SDK available).
      3. CLI (original path).

    Chat does NOT use web tools, so all SDK paths are available.
    """
    db = current_app.db
    data = request.json
    question = data.get("question", "").strip()
    project_id = data.get("project_id")
    model = _validate_model(data.get("model")) or DEFAULT_MODEL
    if not question:
        return jsonify({"error": "Question is required"}), 400

    companies = db.get_companies(project_id=project_id, limit=200)
    stats = db.get_stats(project_id=project_id)
    categories = db.get_category_stats(project_id=project_id)

    # Filter to relevant companies based on message keywords to reduce context
    keywords = {w for w in question.lower().split() if len(w) > 2}
    if keywords:
        relevant = [
            c for c in companies
            if any(
                k in c.get("name", "").lower()
                or k in (c.get("what") or "").lower()
                or k in (c.get("category_name") or "").lower()
                for k in keywords
            )
        ]
        if not relevant:
            relevant = companies[:20]  # Fallback if no keyword match
        else:
            relevant = relevant[:30]  # Cap at 30 relevant companies
    else:
        relevant = companies[:30]

    # Build the taxonomy context (cacheable across chat turns)
    context = f"""You have access to a taxonomy database with {stats['total_companies']} companies across {stats['total_categories']} categories.

Categories: {', '.join(c['name'] + f' ({c["company_count"]})' for c in categories if not c.get('parent_id'))}

Companies (name | category | what they do | tags):
"""
    for c in relevant:
        tags = ', '.join(c.get('tags', []))
        what = (c.get('what') or '')[:80]
        cat = c.get('category_name') or ''
        context += f"- {c['name']} | {cat} | {what} | {tags}\n"

    instructions = """Answer this question using ONLY the data above. Be extremely brief and data-focused.
Rules:
- Use bullet points, not paragraphs
- Include specific company names, numbers, and categories
- Maximum 5-8 bullet points
- No preamble or pleasantries"""

    safe_question = _sanitize_for_prompt(question)

    # --- Path 1: Instructor (SDK + Pydantic + prompt caching) ---
    if instructor_available() and ChatResponse is not None:
        try:
            result, meta = run_instructor(
                f"{instructions}\n\nQuestion: {safe_question}",
                model,
                response_model=ChatResponse,
                timeout=60,
                max_retries=2,
                context=context,
            )
            logger.info("Instructor chat completed in %dms", meta.get("duration_ms", 0))
            return jsonify({"answer": result.answer})
        except Exception as e:
            logger.warning("Instructor chat failed, falling back: %s", e)

    # --- Path 2: SDK with prompt caching ---
    try:
        response = run_sdk_cached(
            f"{instructions}\n\nQuestion: {safe_question}",
            model, timeout=60,
            context=context,
        )
        answer = response.get("result", "")
        return jsonify({"answer": answer})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Request timed out. Try a simpler question."}), 500
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse AI response."}), 500
    except Exception as e:
        # Final fallback: plain run_cli with full prompt
        try:
            full_prompt = f"{context}\n\n{instructions}\n\nQuestion: {safe_question}"
            response = run_cli(full_prompt, model, timeout=60)
            answer = response.get("result", "")
            return jsonify({"answer": answer})
        except Exception as e2:
            logger.error("Chat failed (all paths): %s", e2)
            return jsonify({"error": "An internal error occurred. Check logs for details."}), 500


# --- Market Report ---

def _run_market_report(job_id, category_name, project_id, model):
    report_db = Database()
    companies = report_db.get_companies(project_id=project_id, limit=200)
    cat_companies = [c for c in companies if c.get('category_name') == category_name]

    # Build company summaries, skipping null/N/A fields to reduce token waste
    _COMPANY_FIELDS = [
        ("URL", "url"), ("Description", "what"), ("Target Market", "target"),
        ("Products", "products"), ("Funding", "funding"),
        ("Funding Stage", "funding_stage"), ("Total Raised", "total_funding_usd"),
        ("Geography", "geography"), ("Employees", "employee_range"),
        ("Founded", "founded_year"), ("TAM", "tam"),
    ]
    summaries = []
    for c in cat_companies:
        lines = [f"### {c['name']}"]
        for label, key in _COMPANY_FIELDS:
            val = c.get(key)
            if val and str(val).strip() and str(val).strip() != "N/A":
                lines.append(f"- {label}: {val}")
        # HQ: combine city + country, skip if both empty
        hq_parts = [p for p in (c.get("hq_city", ""), c.get("hq_country", "")) if p]
        if hq_parts:
            lines.append(f"- HQ: {', '.join(hq_parts)}")
        tags = c.get("tags", [])
        if tags:
            lines.append(f"- Tags: {', '.join(tags)}")
        summaries.append("\n".join(lines))
    company_summaries = "\n\n".join(summaries)

    prompt = f"""You are a senior market analyst at a tier-1 research firm (similar to Gartner, IDC, or Mintel). Generate a rigorous, data-driven market intelligence briefing for the "{category_name}" category.

COMPANY DATA (from our proprietary database):
{company_summaries}

INSTRUCTIONS:
1. First, analyze the company data provided above
2. Then, use WebSearch to validate and enrich your findings:
   - Search for recent market reports, funding announcements, or industry trends related to this category
   - Search for market size data (TAM/SAM/SOM) for this sector
   - Search for any recent news about the key companies listed
3. Synthesize everything into a structured analyst briefing

REQUIRED FORMAT (Markdown):

# {category_name}: Market Intelligence Briefing

## Executive Summary
[2-3 sentence overview. Include estimated market size if found via search.]

## Market Landscape
[Include a mermaid quadrant chart showing competitive positioning]

```mermaid
quadrantChart
    title Competitive Positioning
    x-axis Low Market Focus --> High Market Focus
    y-axis Early Stage --> Mature
    [Position companies based on your analysis]
```

## Key Players & Competitive Analysis
[For each significant company: what they do, differentiation, funding stage, and competitive position. Use a markdown table.]

| Company | Focus | Funding Stage | Differentiation |
|---------|-------|--------------|-----------------|
...

## Market Dynamics
### Tailwinds
[3-4 factors driving growth, with citations]

### Headwinds
[2-3 challenges or risks, with citations]

## Funding & Investment Patterns
[Aggregate funding analysis. Include total capital deployed, average round size, most active investors if findable]

## Outlook & Implications
[Forward-looking analysis with points AND counterpoints. What does this mean for insurers/investors/operators?]

## Sources & Citations
[List all web sources consulted with URLs]

CONSTRAINTS:
- Total length: 1500-2000 words (approximately 2 A4 pages)
- Every factual claim from web search must include a citation [Source Name](URL)
- Be specific: use company names, dollar amounts, dates
- Maintain analytical objectivity - present both bull and bear cases
- If you cannot verify a claim via web search, explicitly note it as "per company self-reporting"
"""

    try:
        response = run_cli(
            prompt, model, timeout=300,
            tools="WebSearch,WebFetch",
        )
        report = response.get("result", "")
        result_data = {"status": "complete", "report": report,
                       "category": category_name,
                       "company_count": len(cat_companies)}
    except subprocess.TimeoutExpired:
        result_data = {"status": "error",
                       "error": "Report generation timed out after 5 minutes. Try a smaller category or a faster model."}
    except json.JSONDecodeError:
        result_data = {"status": "error",
                       "error": "Failed to parse AI response. Please try again."}
    except Exception as e:
        logger.error("Market report failed for category %r: %s", category_name, e)
        result_data = {"status": "error", "error": "An internal error occurred. Check logs for details."}

    write_result("report", job_id, result_data)

    if result_data.get("status") == "complete":
        report_db.save_report(
            project_id=project_id or 1, report_id=job_id,
            category_name=category_name,
            company_count=len(cat_companies),
            model=model,
            markdown_content=result_data.get("report", ""),
        )
    elif result_data.get("status") == "error":
        report_db.save_report(
            project_id=project_id or 1, report_id=job_id,
            category_name=category_name,
            company_count=len(cat_companies),
            model=model, markdown_content=None,
            status="error",
            error_message=result_data.get("error", ""),
        )
    sync_to_git_async(f"Report generated: {category_name}")


@ai_bp.route("/api/ai/market-report", methods=["POST"])
def ai_market_report():
    data = request.json
    category_name = data.get("category_name", "").strip()
    project_id = data.get("project_id")
    model = _validate_model(data.get("model")) or RESEARCH_MODEL
    if not category_name:
        return jsonify({"error": "category_name is required"}), 400

    report_id = start_async_job("report", _run_market_report, category_name, project_id, model)
    return jsonify({"report_id": report_id})


@ai_bp.route("/api/ai/market-report/<report_id>")
def get_market_report(report_id):
    return jsonify(poll_result("report", report_id))


# --- Saved Reports ---

@ai_bp.route("/api/reports")
def list_reports():
    project_id = request.args.get("project_id", type=int)
    reports = current_app.db.get_reports(project_id=project_id)
    for r in reports:
        r.pop("markdown_content", None)
    return jsonify(reports)


@ai_bp.route("/api/reports/<report_id>")
def get_report(report_id):
    report = current_app.db.get_report(report_id)
    if not report:
        return jsonify({"error": "Not found"}), 404
    return jsonify(report)


@ai_bp.route("/api/reports/<report_id>", methods=["DELETE"])
def delete_report(report_id):
    current_app.db.delete_report(report_id)
    result_path = DATA_DIR / f"report_{report_id}.json"
    result_path.unlink(missing_ok=True)
    return jsonify({"status": "ok"})


@ai_bp.route("/api/reports/<report_id>/export/md")
def export_report_md(report_id):
    import io
    from flask import send_file
    report = current_app.db.get_report(report_id)
    if not report or not report.get("markdown_content"):
        return jsonify({"error": "Report not found"}), 404
    md = report["markdown_content"]
    buf = io.BytesIO(md.encode("utf-8"))
    buf.seek(0)
    filename = f"report_{report['category_name'].replace(' ', '_')}_{report_id}.md"
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype="text/markdown")
