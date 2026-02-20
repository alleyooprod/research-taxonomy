"""Flask web app for browsing and managing the taxonomy."""
import sys
import time
from collections import defaultdict

import nh3
from flask import Flask, render_template, request, jsonify, g
from flask_talisman import Talisman
from loguru import logger

from config import (
    WEB_HOST, WEB_PORT, DATA_DIR, LOGS_DIR, APP_VERSION,
    generate_csrf_token, verify_csrf_token,
    RATE_LIMIT_WINDOW, RATE_LIMIT_MAX_REQUESTS,
)
from storage.db import Database

LOG_FILE = LOGS_DIR / "app.log"


def _setup_logging():
    """Configure loguru file + stderr logging with rotation."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    # Remove default handler
    logger.remove()
    # Add file handler with rotation
    logger.add(
        str(LOG_FILE),
        rotation="5 MB",
        retention=5,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )
    # Add stderr for dev
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level: <8} | {message}")

    def _exception_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.exception("Unhandled exception: {}", exc_value)

    sys.excepthook = _exception_hook


def sanitize_html(html):
    """Server-side HTML sanitization for LLM output."""
    return nh3.clean(
        html,
        tags={"p", "br", "strong", "em", "ul", "ol", "li", "a",
              "h1", "h2", "h3", "h4", "h5", "h6", "code", "pre",
              "blockquote", "table", "thead", "tbody", "tr", "th", "td",
              "hr", "span", "div", "sup", "sub", "img"},
        attributes={"a": {"href", "target", "rel"}, "img": {"src", "alt"}},
    )

# --- Rate limiting (in-memory, per-process) ---
RATE_LIMIT_MAX_REQUESTS.setdefault("read", 300)
_rate_buckets = defaultdict(list)  # key -> [timestamps]


def _check_rate_limit(key, category="default"):
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    bucket = _rate_buckets[key]
    # Prune old entries
    cutoff = now - RATE_LIMIT_WINDOW
    _rate_buckets[key] = [t for t in bucket if t > cutoff]
    max_req = RATE_LIMIT_MAX_REQUESTS.get(category, 120)
    if len(_rate_buckets[key]) >= max_req:
        return False
    _rate_buckets[key].append(now)
    return True


def _cleanup_stale_results():
    """Remove stale async result files older than 7 days."""
    cutoff = time.time() - 86400 * 7
    prefixes = ("report_", "discover_", "similar_", "reresearch_", "review_", "diagram_",
                 "pricing_", "explore_dim_", "populate_dim_", "landscape_", "gap_")
    try:
        for f in DATA_DIR.iterdir():
            if f.suffix == ".json" and f.name.startswith(prefixes):
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
    except Exception:
        pass


def create_app():
    _setup_logging()
    logger.info("Starting Research Taxonomy Library v%s", APP_VERSION)

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB (evidence uploads)

    # --- Content Security Policy via Flask-Talisman ---
    csp = {
        'default-src': "'self'",
        'script-src': ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com",
                        "esm.sh", "'unsafe-eval'", "'unsafe-inline'"],
        'style-src': ["'self'", "'unsafe-inline'", "cdn.jsdelivr.net",
                       "cdnjs.cloudflare.com", "fonts.googleapis.com", "esm.sh"],
        'font-src': ["'self'", "fonts.gstatic.com", "cdn.jsdelivr.net", "esm.sh"],
        'img-src': ["'self'", "data:", "blob:", "*.tile.openstreetmap.org",
                    "*.basemaps.cartocdn.com", "logo.clearbit.com"],
        'connect-src': ["'self'", "esm.sh"],
        'frame-src': "'none'",
        'object-src': "'none'",
        'base-uri': "'self'",
    }
    Talisman(
        app,
        content_security_policy=csp,
        force_https=False,
        strict_transport_security=False,
        session_cookie_secure=False,
    )

    # Shared database instance (accessed via current_app.db in blueprints)
    app.db = Database()

    _cleanup_stale_results()

    # --- Request logging ---
    @app.before_request
    def _log_request():
        g.request_start = time.time()

    @app.after_request
    def _after_request(response):
        duration = time.time() - getattr(g, "request_start", time.time())
        if request.path.startswith("/api/"):
            logger.info(
                "%s %s %s %.0fms",
                request.method, request.path, response.status_code,
                duration * 1000,
            )
        return response

    # --- Host header validation (prevent DNS rebinding) ---
    @app.before_request
    def _validate_host():
        if request.path.startswith("/api/"):
            # Accept the actual port the server is running on (may differ from
            # WEB_PORT when _find_free_port falls back to another port).
            actual_port = request.server[1] if request.server else WEB_PORT
            allowed_hosts = {
                f"127.0.0.1:{actual_port}", f"localhost:{actual_port}",
                "127.0.0.1", "localhost",
            }
            if request.host not in allowed_hosts:
                return jsonify({"error": "Invalid host"}), 403

    # --- CSRF Protection (signed per-request tokens) ---
    @app.before_request
    def _csrf_check():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        if request.path == "/healthz":
            return
        token = request.headers.get("X-CSRF-Token")
        if not verify_csrf_token(token):
            return jsonify({"error": "Invalid CSRF token"}), 403

    # --- Rate limiting ---
    @app.before_request
    def _rate_limit():
        if app.config.get("TESTING"):
            return  # Skip rate limiting in test mode
        client_key = request.remote_addr or "local"
        if request.method == "GET":
            category = "read"
        else:
            category = "ai" if request.path.startswith("/api/ai/") else "default"
        if not _check_rate_limit(f"{client_key}:{category}", category):
            return jsonify({"error": "Rate limit exceeded. Please wait."}), 429

    # --- Health check ---
    @app.route("/healthz")
    def healthz():
        try:
            app.db.get_projects()
            return jsonify({"status": "ok", "db": "connected"})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 500

    # --- Pages ---
    @app.route("/")
    def index():
        return render_template("index.html", csrf_token=generate_csrf_token(), app_version=APP_VERSION)

    # --- Projects API (small enough to keep in app.py) ---
    @app.route("/api/projects")
    def list_projects():
        return jsonify(app.db.get_projects())

    @app.route("/api/projects", methods=["POST"])
    def create_project():
        from core.schema import SCHEMA_TEMPLATES, DEFAULT_COMPANY_SCHEMA, validate_schema, normalize_schema

        data = request.json
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Project name is required"}), 400

        purpose = data.get("purpose", "")
        outcome = data.get("outcome", "")
        description = data.get("description", "")

        seed_text = data.get("seed_categories", "")
        seed_categories = [c.strip() for c in seed_text.split("\n") if c.strip()]

        links_text = data.get("example_links", "")
        example_links = [l.strip() for l in links_text.split("\n") if l.strip()]

        kw_text = data.get("market_keywords", "")
        market_keywords = [k.strip() for k in kw_text.split(",") if k.strip()]

        # Resolve entity schema: explicit schema > template > default
        entity_schema = data.get("entity_schema")
        template_key = data.get("template")

        if entity_schema:
            # Direct schema provided — validate and normalize
            valid, errors = validate_schema(entity_schema)
            if not valid:
                return jsonify({"error": f"Invalid schema: {'; '.join(errors)}"}), 400
            entity_schema = normalize_schema(entity_schema)
        elif template_key:
            if template_key not in SCHEMA_TEMPLATES:
                return jsonify({"error": f"Unknown template: {template_key}"}), 400
            entity_schema = normalize_schema(SCHEMA_TEMPLATES[template_key]["schema"])
        else:
            # Default: blank company schema
            entity_schema = normalize_schema(DEFAULT_COMPANY_SCHEMA)

        try:
            project_id = app.db.create_project(
                name=name, purpose=purpose, outcome=outcome,
                seed_categories=seed_categories, example_links=example_links,
                market_keywords=market_keywords, description=description,
                entity_schema=entity_schema,
            )
            return jsonify({"id": project_id, "name": name, "status": "ok",
                            "template": template_key or "blank"})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/projects/<int:project_id>")
    def get_project(project_id):
        project = app.db.get_project(project_id)
        if not project:
            return jsonify({"error": "Not found"}), 404
        return jsonify(project)

    @app.route("/api/projects/<int:project_id>", methods=["POST"])
    def update_project(project_id):
        fields = request.json
        app.db.update_project(project_id, fields)
        return jsonify({"status": "ok"})

    @app.route("/api/projects/<int:project_id>/toggle-feature", methods=["POST"])
    def toggle_feature(project_id):
        import json as _json
        data = request.json
        feature = data.get("feature")
        enabled = data.get("enabled", True)
        if not feature:
            return jsonify({"error": "feature is required"}), 400
        project = app.db.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        features = {}
        if project.get("features"):
            try:
                features = _json.loads(project["features"])
            except (ValueError, TypeError):
                features = {}
        features[feature] = enabled
        app.db.update_project(project_id, {"features": _json.dumps(features)})
        return jsonify({"status": "ok", "features": features})

    # --- Register Blueprints ---
    from web.blueprints.companies import companies_bp
    from web.blueprints.taxonomy import taxonomy_bp
    from web.blueprints.processing import processing_bp
    from web.blueprints.ai import ai_bp
    from web.blueprints.data import data_bp
    from web.blueprints.settings import settings_bp
    from web.blueprints.research import research_bp
    from web.blueprints.canvas import canvas_bp
    from web.blueprints.dimensions import dimensions_bp
    from web.blueprints.discovery import discovery_bp
    from web.blueprints.entities import entities_bp
    from web.blueprints.capture import capture_bp
    from web.blueprints.extraction import extraction_bp

    app.register_blueprint(companies_bp)
    app.register_blueprint(taxonomy_bp)
    app.register_blueprint(processing_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(research_bp)
    app.register_blueprint(canvas_bp)
    app.register_blueprint(dimensions_bp)
    app.register_blueprint(discovery_bp)
    app.register_blueprint(entities_bp)
    app.register_blueprint(capture_bp)
    app.register_blueprint(extraction_bp)

    return app


def _register_shutdown():
    """Register cleanup handlers for graceful shutdown."""
    import atexit
    import signal

    def _cleanup():
        try:
            from web.async_jobs import shutdown_pool
            shutdown_pool(wait=False)
        except Exception:
            pass
        try:
            from core.scraper import close_browser_sync
            close_browser_sync()
        except Exception:
            pass

    atexit.register(_cleanup)

    def _signal_handler(signum, frame):
        _cleanup()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


if __name__ == "__main__":
    _register_shutdown()
    app = create_app()
    print(f"\n  Research Taxonomy Library")
    print(f"  http://{WEB_HOST}:{WEB_PORT}\n")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=True)
