"""Entity storage mixin for the Research Workbench.

Handles CRUD for the flexible entity system:
- entity_type_defs: per-project entity type definitions (from schema)
- entities: the actual entity instances
- entity_attributes: timestamped attribute values (temporal versioning)
- entity_relationships: many-to-many relationships between entities
- evidence: captured artefacts linked to entities
"""

import json
from datetime import datetime


class EntityMixin:
    """Database operations for the entity system."""

    # ── Entity Type Definitions ──────────────────────────────────

    def sync_entity_types(self, project_id, schema):
        """Sync entity type definitions from a schema dict to the DB.

        Creates or updates entity_type_defs rows to match the schema.
        Does NOT delete types that exist in DB but not in schema (safety).
        """
        with self._get_conn() as conn:
            self._sync_entity_types_with_conn(conn, project_id, schema)

    def _sync_entity_types_with_conn(self, conn, project_id, schema):
        """Internal: sync entity types using an existing connection."""
        for et in schema.get("entity_types", []):
            conn.execute("""
                INSERT INTO entity_type_defs (project_id, slug, name, description, icon,
                                              parent_type_slug, attributes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, slug) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    icon = excluded.icon,
                    parent_type_slug = excluded.parent_type_slug,
                    attributes_json = excluded.attributes_json,
                    updated_at = datetime('now')
            """, (
                project_id,
                et["slug"],
                et["name"],
                et.get("description", ""),
                et.get("icon", "circle"),
                et.get("parent_type"),
                json.dumps(et.get("attributes", [])),
            ))

        # Sync relationship definitions
        for rel in schema.get("relationships", []):
            conn.execute("""
                INSERT INTO entity_relationship_defs (project_id, name, from_type_slug,
                                                      to_type_slug, description)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, name) DO UPDATE SET
                    from_type_slug = excluded.from_type_slug,
                    to_type_slug = excluded.to_type_slug,
                    description = excluded.description
            """, (
                project_id,
                rel["name"],
                rel["from_type"],
                rel["to_type"],
                rel.get("description", ""),
            ))

    def get_entity_type_defs(self, project_id):
        """Get all entity type definitions for a project."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM entity_type_defs
                WHERE project_id = ?
                ORDER BY id
            """, (project_id,)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["attributes"] = json.loads(d.pop("attributes_json", "[]"))
                result.append(d)
            return result

    def get_entity_type_def(self, project_id, type_slug):
        """Get a single entity type definition."""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT * FROM entity_type_defs
                WHERE project_id = ? AND slug = ?
            """, (project_id, type_slug)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["attributes"] = json.loads(d.pop("attributes_json", "[]"))
            return d

    # ── Entities ─────────────────────────────────────────────────

    def create_entity(self, project_id, type_slug, name, parent_entity_id=None,
                      category_id=None, attributes=None, source="manual"):
        """Create a new entity and optionally set initial attributes.

        Args:
            project_id: Project ID
            type_slug: Entity type slug (e.g. 'company', 'product')
            name: Display name
            parent_entity_id: Parent entity ID (for hierarchy)
            category_id: Taxonomy category ID (optional)
            attributes: Dict of {attr_slug: value} for initial attributes
            source: 'manual', 'ai', 'import', 'migration'

        Returns: entity ID
        """
        slug = self._make_slug(name)
        now = datetime.now().isoformat()

        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO entities (project_id, type_slug, name, slug,
                                      parent_entity_id, category_id,
                                      created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (project_id, type_slug, name, slug,
                  parent_entity_id, category_id, now, now))
            entity_id = cursor.lastrowid

            # Set initial attributes
            if attributes:
                for attr_slug, value in attributes.items():
                    if value is not None:
                        self._set_attribute(conn, entity_id, attr_slug, value,
                                            source=source, captured_at=now)

            return entity_id

    def get_entity(self, entity_id):
        """Get a single entity with its current attribute values."""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT e.*, etd.name as type_name, etd.icon as type_icon
                FROM entities e
                LEFT JOIN entity_type_defs etd
                    ON etd.project_id = e.project_id AND etd.slug = e.type_slug
                WHERE e.id = ? AND e.is_deleted = 0
            """, (entity_id,)).fetchone()
            if not row:
                return None

            entity = dict(row)
            entity["attributes"] = self._get_current_attributes(conn, entity_id)
            entity["child_count"] = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE parent_entity_id = ? AND is_deleted = 0",
                (entity_id,)
            ).fetchone()[0]
            entity["evidence_count"] = conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE entity_id = ?",
                (entity_id,)
            ).fetchone()[0]
            return entity

    def get_entities(self, project_id, type_slug=None, parent_entity_id=None,
                     category_id=None, search=None, sort_by="name",
                     include_attributes=True, limit=None, offset=None):
        """Get entities with filtering, sorting, and pagination.

        Args:
            project_id: Project ID
            type_slug: Filter by entity type
            parent_entity_id: Filter by parent (use 'root' for top-level)
            category_id: Filter by taxonomy category
            search: Search in name
            sort_by: 'name', 'created_at', 'updated_at'
            include_attributes: Whether to load current attributes
            limit: Max results
            offset: Skip N results

        Returns: list of entity dicts
        """
        conditions = ["e.project_id = ?", "e.is_deleted = 0"]
        params = [project_id]

        if type_slug:
            conditions.append("e.type_slug = ?")
            params.append(type_slug)

        if parent_entity_id == "root":
            conditions.append("e.parent_entity_id IS NULL")
        elif parent_entity_id is not None:
            conditions.append("e.parent_entity_id = ?")
            params.append(parent_entity_id)

        if category_id:
            conditions.append("e.category_id = ?")
            params.append(category_id)

        if search:
            conditions.append("e.name LIKE ?")
            params.append(f"%{search}%")

        where = " AND ".join(conditions)

        sort_map = {
            "name": "e.name ASC",
            "created_at": "e.created_at DESC",
            "updated_at": "e.updated_at DESC",
        }
        order = sort_map.get(sort_by, "e.name ASC")

        sql = f"""
            SELECT e.*, etd.name as type_name, etd.icon as type_icon,
                   (SELECT COUNT(*) FROM entities c
                    WHERE c.parent_entity_id = e.id AND c.is_deleted = 0) as child_count,
                   (SELECT COUNT(*) FROM evidence ev
                    WHERE ev.entity_id = e.id) as evidence_count
            FROM entities e
            LEFT JOIN entity_type_defs etd
                ON etd.project_id = e.project_id AND etd.slug = e.type_slug
            WHERE {where}
            ORDER BY {order}
        """

        if limit:
            sql += " LIMIT ?"
            params.append(limit)
            if offset:
                sql += " OFFSET ?"
                params.append(offset)

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            entities = []
            for r in rows:
                entity = dict(r)
                if include_attributes:
                    entity["attributes"] = self._get_current_attributes(conn, entity["id"])
                entities.append(entity)
            return entities

    def update_entity(self, entity_id, fields):
        """Update entity core fields (name, category_id, parent_entity_id).

        For attribute updates, use set_entity_attribute() instead.
        """
        allowed = {"name", "slug", "category_id", "parent_entity_id", "is_starred"}
        safe = {k: v for k, v in fields.items() if k in allowed}
        if not safe:
            return

        if "name" in safe and "slug" not in safe:
            safe["slug"] = self._make_slug(safe["name"])

        safe["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in safe)
        values = list(safe.values()) + [entity_id]

        with self._get_conn() as conn:
            conn.execute(f"UPDATE entities SET {set_clause} WHERE id = ?", values)

    def delete_entity(self, entity_id, cascade=True):
        """Soft-delete an entity. If cascade, also soft-deletes children."""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            self._delete_entity_recursive(conn, entity_id, now, cascade)

    def _delete_entity_recursive(self, conn, entity_id, now, cascade):
        """Internal: recursive soft-delete using an existing connection."""
        conn.execute("""
            UPDATE entities SET is_deleted = 1, deleted_at = ?
            WHERE id = ?
        """, (now, entity_id))

        if cascade:
            children = conn.execute(
                "SELECT id FROM entities WHERE parent_entity_id = ? AND is_deleted = 0",
                (entity_id,)
            ).fetchall()
            for child in children:
                self._delete_entity_recursive(conn, child["id"], now, cascade)

    def restore_entity(self, entity_id):
        """Restore a soft-deleted entity."""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE entities SET is_deleted = 0, deleted_at = NULL
                WHERE id = ?
            """, (entity_id,))

    # ── Entity Attributes (Temporal) ─────────────────────────────

    def set_entity_attribute(self, entity_id, attr_slug, value,
                             source="manual", confidence=None,
                             captured_at=None, snapshot_id=None):
        """Set an attribute value for an entity.

        This creates a new timestamped record — previous values are preserved
        for temporal querying.
        """
        with self._get_conn() as conn:
            self._set_attribute(conn, entity_id, attr_slug, value,
                                source=source, confidence=confidence,
                                captured_at=captured_at, snapshot_id=snapshot_id)
            conn.execute(
                "UPDATE entities SET updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), entity_id)
            )

    def set_entity_attributes(self, entity_id, attributes, source="manual",
                              confidence=None, snapshot_id=None):
        """Set multiple attributes at once (same capture timestamp).

        Args:
            entity_id: Entity ID
            attributes: Dict of {attr_slug: value}
            source: 'manual', 'ai', 'import', 'scrape'
            confidence: Optional confidence score (0-1)
            snapshot_id: Optional snapshot grouping ID
        """
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            for attr_slug, value in attributes.items():
                if value is not None:
                    self._set_attribute(conn, entity_id, attr_slug, value,
                                        source=source, confidence=confidence,
                                        captured_at=now, snapshot_id=snapshot_id)
            conn.execute(
                "UPDATE entities SET updated_at = ? WHERE id = ?",
                (now, entity_id)
            )

    def get_entity_attribute_history(self, entity_id, attr_slug, limit=50):
        """Get historical values for an attribute (newest first)."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM entity_attributes
                WHERE entity_id = ? AND attr_slug = ?
                ORDER BY captured_at DESC
                LIMIT ?
            """, (entity_id, attr_slug, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_entity_attributes_at(self, entity_id, at_date):
        """Get all attributes as they were at a specific point in time.

        Returns dict of {attr_slug: value} with the most recent value
        on or before at_date.
        """
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT attr_slug, value, source, confidence, captured_at
                FROM entity_attributes
                WHERE entity_id = ? AND captured_at <= ?
                AND id IN (
                    SELECT MAX(id) FROM entity_attributes
                    WHERE entity_id = ? AND captured_at <= ?
                    GROUP BY attr_slug
                )
            """, (entity_id, at_date, entity_id, at_date)).fetchall()
            return {r["attr_slug"]: {
                "value": r["value"],
                "source": r["source"],
                "confidence": r["confidence"],
                "captured_at": r["captured_at"],
            } for r in rows}

    # ── Entity Relationships (Graph) ─────────────────────────────

    def create_entity_relationship(self, from_entity_id, to_entity_id,
                                   relationship_type, metadata=None):
        """Create a many-to-many relationship between two entities."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO entity_relationships
                    (from_entity_id, to_entity_id, relationship_type, metadata_json)
                VALUES (?, ?, ?, ?)
            """, (from_entity_id, to_entity_id, relationship_type,
                  json.dumps(metadata or {})))

    def get_entity_relationships(self, entity_id, direction="both"):
        """Get relationships for an entity.

        Args:
            entity_id: Entity ID
            direction: 'outgoing', 'incoming', or 'both'
        """
        with self._get_conn() as conn:
            results = []

            if direction in ("outgoing", "both"):
                rows = conn.execute("""
                    SELECT er.*, e.name as related_name, e.type_slug as related_type
                    FROM entity_relationships er
                    JOIN entities e ON e.id = er.to_entity_id
                    WHERE er.from_entity_id = ?
                """, (entity_id,)).fetchall()
                for r in rows:
                    d = dict(r)
                    d["direction"] = "outgoing"
                    d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
                    results.append(d)

            if direction in ("incoming", "both"):
                rows = conn.execute("""
                    SELECT er.*, e.name as related_name, e.type_slug as related_type
                    FROM entity_relationships er
                    JOIN entities e ON e.id = er.from_entity_id
                    WHERE er.to_entity_id = ?
                """, (entity_id,)).fetchall()
                for r in rows:
                    d = dict(r)
                    d["direction"] = "incoming"
                    d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
                    results.append(d)

            return results

    def delete_entity_relationship(self, relationship_id):
        """Delete a relationship."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM entity_relationships WHERE id = ?",
                         (relationship_id,))

    # ── Evidence ─────────────────────────────────────────────────

    def add_evidence(self, entity_id, evidence_type, file_path,
                     source_url=None, source_name=None, metadata=None,
                     captured_at=None):
        """Add an evidence artefact linked to an entity.

        Args:
            entity_id: Entity ID
            evidence_type: 'screenshot', 'document', 'page_archive', 'video', 'other'
            file_path: Path to the stored file (relative to project evidence dir)
            source_url: Original URL where this was captured from
            source_name: Human-readable source (e.g. 'Mobbin', 'App Store')
            metadata: Additional JSON metadata
            captured_at: When the evidence was captured

        Returns: evidence ID
        """
        now = captured_at or datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO evidence (entity_id, evidence_type, file_path,
                                      source_url, source_name, metadata_json,
                                      captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (entity_id, evidence_type, file_path,
                  source_url, source_name, json.dumps(metadata or {}), now))
            return cursor.lastrowid

    def get_evidence(self, entity_id=None, evidence_type=None,
                     source_name=None, limit=100):
        """Get evidence items with optional filtering."""
        conditions = []
        params = []

        if entity_id:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        if evidence_type:
            conditions.append("evidence_type = ?")
            params.append(evidence_type)
        if source_name:
            conditions.append("source_name = ?")
            params.append(source_name)

        where = " AND ".join(conditions) if conditions else "1=1"

        with self._get_conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM evidence
                WHERE {where}
                ORDER BY captured_at DESC
                LIMIT ?
            """, params + [limit]).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
                result.append(d)
            return result

    def delete_evidence(self, evidence_id):
        """Delete an evidence record (does not delete the file)."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM evidence WHERE id = ?", (evidence_id,))

    # ── Snapshots ────────────────────────────────────────────────

    def create_snapshot(self, project_id, description=None):
        """Create a capture snapshot (groups attribute updates from a single session).

        Returns: snapshot_id
        """
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO entity_snapshots (project_id, description)
                VALUES (?, ?)
            """, (project_id, description))
            return cursor.lastrowid

    def get_snapshots(self, project_id, limit=50):
        """Get capture snapshots for a project (newest first)."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT s.*,
                    (SELECT COUNT(*) FROM entity_attributes a WHERE a.snapshot_id = s.id)
                    as attribute_count
                FROM entity_snapshots s
                WHERE s.project_id = ?
                ORDER BY s.created_at DESC
                LIMIT ?
            """, (project_id, limit)).fetchall()
            return [dict(r) for r in rows]

    # ── Stats ────────────────────────────────────────────────────

    def get_entity_stats(self, project_id):
        """Get entity counts per type for a project."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT type_slug, COUNT(*) as count
                FROM entities
                WHERE project_id = ? AND is_deleted = 0
                GROUP BY type_slug
            """, (project_id,)).fetchall()
            return {r["type_slug"]: r["count"] for r in rows}

    # ── Internal Helpers ─────────────────────────────────────────

    def _set_attribute(self, conn, entity_id, attr_slug, value,
                       source="manual", confidence=None,
                       captured_at=None, snapshot_id=None):
        """Internal: insert a timestamped attribute value."""
        now = captured_at or datetime.now().isoformat()

        # Serialize non-string values
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        elif isinstance(value, bool):
            value = "1" if value else "0"
        elif value is not None:
            value = str(value)

        conn.execute("""
            INSERT INTO entity_attributes
                (entity_id, attr_slug, value, source, confidence,
                 captured_at, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (entity_id, attr_slug, value, source, confidence,
              now, snapshot_id))

    def _get_current_attributes(self, conn, entity_id):
        """Internal: get the most recent value for each attribute of an entity."""
        rows = conn.execute("""
            SELECT attr_slug, value, source, confidence, captured_at
            FROM entity_attributes
            WHERE entity_id = ?
            AND id IN (
                SELECT MAX(id) FROM entity_attributes
                WHERE entity_id = ?
                GROUP BY attr_slug
            )
        """, (entity_id, entity_id)).fetchall()
        return {r["attr_slug"]: {
            "value": r["value"],
            "source": r["source"],
            "confidence": r["confidence"],
            "captured_at": r["captured_at"],
        } for r in rows}
