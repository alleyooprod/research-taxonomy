"""Data API: export, import, stats, charts, filters, tags, views, map layouts."""
import csv
import io

from flask import Blueprint, current_app, jsonify, request, send_file

from core.git_sync import sync_to_git_async
from storage.export import export_csv, export_json, export_markdown
from web.notifications import notify_sse

data_bp = Blueprint("data", __name__)


# --- Export ---

@data_bp.route("/api/export/json")
def download_json():
    project_id = request.args.get("project_id", type=int)
    path = export_json(current_app.db, project_id=project_id)
    return send_file(path, as_attachment=True, download_name="taxonomy_data.json")


@data_bp.route("/api/export/md")
def download_md():
    project_id = request.args.get("project_id", type=int)
    path = export_markdown(current_app.db, project_id=project_id)
    return send_file(path, as_attachment=True, download_name="taxonomy_master.md")


@data_bp.route("/api/export/csv")
def download_csv():
    project_id = request.args.get("project_id", type=int)
    path = export_csv(current_app.db, project_id=project_id)
    return send_file(path, as_attachment=True, download_name="taxonomy_export.csv")


# --- CSV Import ---

@data_bp.route("/api/import/csv", methods=["POST"])
def import_csv():
    db = current_app.db
    project_id = request.form.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB
    content_bytes = file.stream.read(MAX_CSV_SIZE + 1)
    if len(content_bytes) > MAX_CSV_SIZE:
        return jsonify({"error": "CSV file too large (max 10MB)"}), 400
    content = content_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if len(rows) > 10000:
        return jsonify({"error": "Too many rows (max 10,000)"}), 400
    imported = db.import_companies_from_rows(rows, project_id)
    db.log_activity(project_id, "csv_imported",
                    f"Imported {imported} companies from CSV ({len(rows)} rows)",
                    "project", project_id)
    notify_sse(project_id, "company_added",
               {"count": imported, "source": "csv_import"})
    sync_to_git_async(f"CSV import: {imported} companies")
    return jsonify({"imported": imported, "total_rows": len(rows)})


# --- Stats & Charts ---

@data_bp.route("/api/stats")
def get_stats():
    project_id = request.args.get("project_id", type=int)
    return jsonify(current_app.db.get_stats(project_id=project_id))


@data_bp.route("/api/charts/data")
def chart_data():
    db = current_app.db
    project_id = request.args.get("project_id", type=int)
    companies = db.get_companies(project_id=project_id)
    categories = db.get_categories(project_id=project_id)

    cat_dist = {}
    for cat in categories:
        if not cat.get("parent_id"):
            cat_dist[cat["name"]] = cat.get("company_count", 0)

    stage_dist = {}
    geo_dist = {}
    confidence_buckets = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
    biz_model_dist = {}

    for c in companies:
        stage = c.get("funding_stage") or "Unknown"
        stage_dist[stage] = stage_dist.get(stage, 0) + 1

        geo = c.get("hq_country") or c.get("geography") or "Unknown"
        geo_dist[geo] = geo_dist.get(geo, 0) + 1

        conf = (c.get("confidence_score") or 0) * 100
        if conf < 20: confidence_buckets["0-20"] += 1
        elif conf < 40: confidence_buckets["20-40"] += 1
        elif conf < 60: confidence_buckets["40-60"] += 1
        elif conf < 80: confidence_buckets["60-80"] += 1
        else: confidence_buckets["80-100"] += 1

        bm = c.get("business_model") or "Unknown"
        biz_model_dist[bm] = biz_model_dist.get(bm, 0) + 1

    return jsonify({
        "category_distribution": cat_dist,
        "funding_stage_distribution": stage_dist,
        "geographic_distribution": geo_dist,
        "confidence_buckets": confidence_buckets,
        "business_model_distribution": biz_model_dist,
        "total_companies": len(companies),
        "total_categories": len([c for c in categories if not c.get("parent_id")]),
    })


# --- Filter Metadata ---

@data_bp.route("/api/filters/options")
def filter_options():
    db = current_app.db
    project_id = request.args.get("project_id", type=int)
    return jsonify({
        "tags": db.get_all_tags(project_id=project_id),
        "geographies": db.get_distinct_geographies(project_id=project_id),
        "funding_stages": db.get_distinct_funding_stages(project_id=project_id),
    })


# --- Tags ---

@data_bp.route("/api/tags")
def list_tags():
    project_id = request.args.get("project_id", type=int)
    return jsonify(current_app.db.get_all_tags(project_id=project_id))


@data_bp.route("/api/tags/rename", methods=["POST"])
def rename_tag():
    db = current_app.db
    data = request.json or {}
    old_tag = data.get("old_tag", "").strip()
    new_tag = data.get("new_tag", "").strip()
    project_id = data.get("project_id")
    if not old_tag or not new_tag:
        return jsonify({"error": "Both old_tag and new_tag are required"}), 400
    updated = db.rename_tag(old_tag, new_tag, project_id=project_id)
    if project_id:
        db.log_activity(project_id, "tag_renamed",
                        f"Renamed tag '{old_tag}' to '{new_tag}' ({updated} companies)",
                        "tag", None)
    return jsonify({"updated": updated})


@data_bp.route("/api/tags/merge", methods=["POST"])
def merge_tags():
    db = current_app.db
    data = request.json or {}
    source = data.get("source_tag", "").strip()
    target = data.get("target_tag", "").strip()
    project_id = data.get("project_id")
    if not source or not target:
        return jsonify({"error": "Both source_tag and target_tag are required"}), 400
    updated = db.merge_tags(source, target, project_id=project_id)
    if project_id:
        db.log_activity(project_id, "tag_merged",
                        f"Merged tag '{source}' into '{target}' ({updated} companies)",
                        "tag", None)
    return jsonify({"updated": updated})


@data_bp.route("/api/tags/delete", methods=["POST"])
def delete_tag():
    db = current_app.db
    data = request.json or {}
    tag_name = data.get("tag", "").strip()
    project_id = data.get("project_id")
    if not tag_name:
        return jsonify({"error": "Tag name required"}), 400
    updated = db.delete_tag(tag_name, project_id=project_id)
    return jsonify({"updated": updated})


# --- Saved Views ---

@data_bp.route("/api/views")
def list_views():
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify([])
    return jsonify(current_app.db.get_saved_views(project_id))


@data_bp.route("/api/views", methods=["POST"])
def save_view():
    data = request.json or {}
    project_id = data.get("project_id")
    name = data.get("name", "").strip()
    filters = data.get("filters", {})
    if not project_id or not name:
        return jsonify({"error": "project_id and name are required"}), 400
    current_app.db.save_view(project_id, name, filters)
    return jsonify({"status": "ok"})


@data_bp.route("/api/views/<int:view_id>", methods=["DELETE"])
def delete_view(view_id):
    current_app.db.delete_saved_view(view_id)
    return jsonify({"status": "ok"})


# --- Map Layouts ---

@data_bp.route("/api/map-layouts")
def list_map_layouts():
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify([])
    return jsonify(current_app.db.get_map_layouts(project_id))


@data_bp.route("/api/map-layouts", methods=["POST"])
def save_map_layout():
    data = request.json or {}
    project_id = data.get("project_id")
    name = data.get("name", "Default")
    layout_data = data.get("layout_data", {})
    if not project_id:
        return jsonify({"error": "project_id required"}), 400
    current_app.db.save_map_layout(project_id, name, layout_data)
    return jsonify({"status": "ok"})
