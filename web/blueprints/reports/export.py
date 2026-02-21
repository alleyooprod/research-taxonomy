"""Report export — HTML, JSON, Markdown, PDF, Canvas formats."""
import hashlib
import json
import uuid

from flask import request, jsonify, current_app, Response
from loguru import logger

from . import reports_bp
from ._shared import _ensure_table, _row_to_report

# ═══════════════════════════════════════════════════════════════
# Report Export
# ═══════════════════════════════════════════════════════════════

@reports_bp.route("/api/synthesis/<int:report_id>/export")
def export_report(report_id):
    """Export a report in the specified format.

    Query: ?format=html|json|markdown|pdf|canvas  (default: json)

    Returns:
        html: standalone HTML document
        json: raw JSON of the report data
        markdown: formatted markdown
        pdf: PDF document (requires weasyprint)
        canvas: Excalidraw-compatible JSON for the Canvas tab
    """
    export_format = request.args.get("format", "json").lower()

    if export_format not in ("html", "json", "markdown", "pdf", "canvas"):
        return jsonify({"error": f"Invalid format: {export_format}. Use html, json, markdown, pdf, or canvas."}), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_table(conn)
        row = conn.execute(
            """
            SELECT id, project_id, template, title, content_json,
                   generated_at, updated_at, is_ai_generated, metadata_json
            FROM workbench_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()

    if not row:
        return jsonify({"error": f"Report {report_id} not found"}), 404

    report = _row_to_report(row)

    if export_format == "json":
        return jsonify(report)

    elif export_format == "markdown":
        md = _report_to_markdown(report)
        return Response(
            md,
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{_safe_filename(report["title"])}.md"'},
        )

    elif export_format == "html":
        html = _report_to_html(report)
        return Response(
            html,
            mimetype="text/html",
            headers={"Content-Disposition": f'attachment; filename="{_safe_filename(report["title"])}.html"'},
        )

    elif export_format == "canvas":
        canvas_data = _report_to_canvas(report)
        return jsonify(canvas_data)

    elif export_format == "pdf":
        try:
            import weasyprint
        except ImportError:
            return jsonify({
                "error": "PDF export requires weasyprint. Install with: pip install weasyprint"
            }), 501

        html = _report_to_pdf_html(report)
        pdf_bytes = weasyprint.HTML(string=html).write_pdf()
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{_safe_filename(report["title"])}.pdf"'},
        )


def _safe_filename(title):
    """Convert a title to a safe filename."""
    safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "" for c in title)
    return safe.strip().replace(" ", "_")[:80] or "report"


def _report_to_markdown(report):
    """Convert a report to Markdown format."""
    lines = []
    lines.append(f"# {report['title']}")
    lines.append("")

    ai_label = " (AI-generated)" if report.get("is_ai_generated") else ""
    lines.append(f"*Generated: {report['generated_at']}{ai_label}*")
    lines.append(f"*Template: {report['template']}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    for section in report.get("sections", []):
        lines.append(f"## {section['heading']}")
        lines.append("")
        content = section.get("content", "")
        lines.append(content)
        lines.append("")

        evidence_refs = section.get("evidence_refs", [])
        if evidence_refs:
            lines.append(f"*Evidence references: {', '.join(str(r) for r in evidence_refs)}*")
            lines.append("")

    lines.append("---")
    lines.append(f"*Report ID: {report['id']}*")

    return "\n".join(lines)


def _report_to_html(report):
    """Convert a report to a standalone HTML document with inline CSS."""
    ai_label = " (AI-generated)" if report.get("is_ai_generated") else ""

    sections_html = []
    for section in report.get("sections", []):
        content = section.get("content", "")
        # Convert simple line breaks and list items to HTML
        content_html = _text_to_html(content)
        evidence_refs = section.get("evidence_refs", [])
        evidence_html = ""
        if evidence_refs:
            evidence_html = (
                f'<p class="evidence-refs">Evidence references: '
                f'{", ".join(str(r) for r in evidence_refs)}</p>'
            )
        sections_html.append(
            f'<section>\n'
            f'  <h2>{_escape_html(section["heading"])}</h2>\n'
            f'  <div class="content">{content_html}</div>\n'
            f'  {evidence_html}\n'
            f'</section>'
        )

    body = "\n".join(sections_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_escape_html(report['title'])}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 24px;
            color: #1a1a1a;
            line-height: 1.6;
            background: #fff;
        }}
        h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
            border-bottom: 2px solid #1a1a1a;
            padding-bottom: 12px;
        }}
        .meta {{
            color: #666;
            font-size: 14px;
            margin-bottom: 32px;
        }}
        section {{
            margin-bottom: 32px;
        }}
        h2 {{
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 12px;
            border-bottom: 1px solid #e0e0e0;
            padding-bottom: 6px;
        }}
        .content {{
            white-space: pre-wrap;
            font-size: 15px;
        }}
        .content p {{
            margin-bottom: 8px;
        }}
        .content ul {{
            margin: 8px 0 8px 24px;
        }}
        .content li {{
            margin-bottom: 4px;
        }}
        .evidence-refs {{
            color: #888;
            font-size: 13px;
            font-style: italic;
            margin-top: 8px;
        }}
        .footer {{
            margin-top: 48px;
            padding-top: 16px;
            border-top: 1px solid #e0e0e0;
            color: #999;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <h1>{_escape_html(report['title'])}</h1>
    <div class="meta">
        Generated: {report['generated_at']}{ai_label}<br>
        Template: {report['template']}
    </div>

    {body}

    <div class="footer">
        Report ID: {report['id']}
    </div>
</body>
</html>"""


def _escape_html(text):
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _text_to_html(text):
    """Convert plain text content to simple HTML."""
    if not text:
        return ""
    text = _escape_html(text)
    lines = text.split("\n")
    html_lines = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if stripped:
                html_lines.append(f"<p>{line}</p>")
            else:
                html_lines.append("")
    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def _report_to_pdf_html(report):
    """Convert a report to an HTML document styled for PDF rendering via weasyprint."""
    ai_label = " (AI-generated)" if report.get("is_ai_generated") else ""

    sections_html = []
    for section in report.get("sections", []):
        content = section.get("content", "")
        content_html = _text_to_html(content)
        evidence_refs = section.get("evidence_refs", [])
        evidence_html = ""
        if evidence_refs:
            evidence_html = (
                f'<p class="evidence-refs">Evidence references: '
                f'{", ".join(str(r) for r in evidence_refs)}</p>'
            )
        sections_html.append(
            f'<section>\n'
            f'  <h2>{_escape_html(section["heading"])}</h2>\n'
            f'  <div class="content">{content_html}</div>\n'
            f'  {evidence_html}\n'
            f'</section>'
        )

    body = "\n".join(sections_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{_escape_html(report['title'])}</title>
    <style>
        @page {{ size: A4; margin: 2cm; }}
        body {{
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #111;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px;
            line-height: 1.6;
        }}
        h1 {{
            font-size: 28px;
            font-weight: 700;
            border-bottom: 2px solid #111;
            padding-bottom: 8px;
            margin-bottom: 8px;
        }}
        .meta {{
            color: #666;
            font-size: 13px;
            margin-bottom: 32px;
        }}
        h2 {{
            font-size: 20px;
            font-weight: 600;
            margin-top: 32px;
            margin-bottom: 12px;
        }}
        p, li {{
            font-size: 14px;
            line-height: 1.6;
        }}
        p {{
            margin-bottom: 6px;
        }}
        ul {{
            margin: 8px 0 8px 24px;
        }}
        li {{
            margin-bottom: 4px;
        }}
        code {{
            font-family: monospace;
            background: #f0f0f0;
            padding: 2px 4px;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 16px 0;
        }}
        th, td {{
            border: 1px solid #ccc;
            padding: 8px;
            text-align: left;
            font-size: 13px;
        }}
        th {{
            background: #f5f5f5;
            font-weight: 600;
        }}
        section {{
            margin-bottom: 24px;
        }}
        .content {{
            white-space: pre-wrap;
        }}
        .evidence-refs {{
            color: #888;
            font-size: 12px;
            font-style: italic;
            margin-top: 8px;
        }}
        .footer {{
            margin-top: 48px;
            padding-top: 16px;
            border-top: 1px solid #ccc;
            color: #999;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <h1>{_escape_html(report['title'])}</h1>
    <div class="meta">
        Generated: {report['generated_at']}{ai_label}<br>
        Template: {report['template']}
    </div>

    {body}

    <div class="footer">
        Report ID: {report['id']}
    </div>
</body>
</html>"""


# ── Canvas (Excalidraw) composition helpers ──────────────────

def _canvas_element_id():
    """Generate a short unique ID for an Excalidraw element."""
    return uuid.uuid4().hex[:8]


def _canvas_seed():
    """Generate a random seed for Excalidraw element rendering."""
    import random
    return random.randint(1, 2147483647)


def _canvas_text_wrap(text, max_chars=80):
    """Wrap text to fit within a maximum character width.

    Preserves existing newlines and wraps long lines at word boundaries.
    """
    if not text:
        return ""
    result_lines = []
    for line in text.split("\n"):
        if len(line) <= max_chars:
            result_lines.append(line)
        else:
            # Word-wrap long lines
            words = line.split(" ")
            current = ""
            for word in words:
                if current and len(current) + 1 + len(word) > max_chars:
                    result_lines.append(current)
                    current = word
                else:
                    current = current + " " + word if current else word
            if current:
                result_lines.append(current)
    return "\n".join(result_lines)


def _make_canvas_element(element_type, overrides):
    """Create a base Excalidraw element with sensible defaults."""
    base = {
        "id": _canvas_element_id(),
        "type": element_type,
        "x": 0,
        "y": 0,
        "width": 100,
        "height": 40,
        "angle": 0,
        "strokeColor": "#000000",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "seed": _canvas_seed(),
        "version": 1,
        "versionNonce": _canvas_seed(),
        "isDeleted": False,
        "boundElements": None,
        "updated": 1,
        "link": None,
        "locked": False,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
    }

    if element_type == "text":
        text = overrides.get("text", "")
        font_size = overrides.get("fontSize", 16)
        lines = text.split("\n") if text else [""]
        char_w = font_size * 0.6
        longest = max(lines, key=len) if lines else ""
        w = max(int(len(longest) * char_w) + 4, 20)
        h = max(int(len(lines) * font_size * 1.5) + 4, font_size + 4)
        base.update({
            "text": text,
            "originalText": text,
            "fontSize": font_size,
            "fontFamily": 3,  # monospace
            "textAlign": "left",
            "verticalAlign": "top",
            "containerId": None,
            "autoResize": True,
            "lineHeight": 1.25,
            "width": w,
            "height": h,
            "backgroundColor": "transparent",
        })

    base.update(overrides)

    # Ensure originalText stays in sync
    if element_type == "text" and "text" in base:
        base["originalText"] = base["text"]

    return base


def _report_to_canvas(report):
    """Convert a report to an Excalidraw-compatible JSON structure.

    Layout: vertical stack, left-aligned, monochrome.
    - Title in a bordered rectangle at the top
    - Each section: heading text + body text below
    """
    elements = []
    x_start = 60
    y_cursor = 60
    canvas_width = 800

    title = report.get("title") or "Untitled Report"
    sections = report.get("sections") or []

    # ── Title block: rectangle + bound text ──
    title_rect_id = _canvas_element_id()
    title_text_id = _canvas_element_id()
    title_font_size = 28
    title_lines = title.split("\n") if title else [""]
    title_text_h = max(int(len(title_lines) * title_font_size * 1.5) + 4, 40)
    title_rect_h = max(60, title_text_h + 20)

    elements.append(_make_canvas_element("rectangle", {
        "id": title_rect_id,
        "x": x_start,
        "y": y_cursor,
        "width": canvas_width,
        "height": title_rect_h,
        "strokeColor": "#000000",
        "backgroundColor": "#ffffff",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "boundElements": [{"type": "text", "id": title_text_id}],
    }))

    elements.append(_make_canvas_element("text", {
        "id": title_text_id,
        "x": x_start,
        "y": y_cursor,
        "width": canvas_width,
        "height": title_rect_h,
        "text": title,
        "fontSize": title_font_size,
        "fontFamily": 3,
        "textAlign": "center",
        "verticalAlign": "middle",
        "containerId": title_rect_id,
        "strokeColor": "#000000",
    }))

    y_cursor += title_rect_h + 40

    # ── Sections ──
    for section in sections:
        heading = section.get("heading") or ""
        content = section.get("content") or ""

        # Section heading
        if heading:
            heading_font_size = 20
            heading_wrapped = _canvas_text_wrap(heading, max_chars=80)
            heading_lines = heading_wrapped.split("\n")
            heading_w = max(int(len(max(heading_lines, key=len)) * heading_font_size * 0.6) + 4, 100)
            heading_h = max(int(len(heading_lines) * heading_font_size * 1.5) + 4, heading_font_size + 4)

            elements.append(_make_canvas_element("text", {
                "x": x_start,
                "y": y_cursor,
                "width": heading_w,
                "height": heading_h,
                "text": heading_wrapped,
                "fontSize": heading_font_size,
                "fontFamily": 3,
                "strokeColor": "#000000",
            }))

            y_cursor += heading_h + 16

        # Section content
        if content:
            content_font_size = 14
            content_wrapped = _canvas_text_wrap(content, max_chars=80)
            content_lines = content_wrapped.split("\n")
            content_w = max(int(len(max(content_lines, key=len)) * content_font_size * 0.6) + 4, 100)
            content_h = max(int(len(content_lines) * content_font_size * 1.5) + 4, content_font_size + 4)

            elements.append(_make_canvas_element("text", {
                "x": x_start,
                "y": y_cursor,
                "width": content_w,
                "height": content_h,
                "text": content_wrapped,
                "fontSize": content_font_size,
                "fontFamily": 3,
                "strokeColor": "#000000",
            }))

            y_cursor += content_h + 40

        # Extra spacing if no content but heading present
        if heading and not content:
            y_cursor += 24

    return {
        "type": "excalidraw",
        "version": 2,
        "source": "research-workbench",
        "elements": elements,
        "appState": {
            "viewBackgroundColor": "#ffffff",
            "gridSize": None,
        },
    }
