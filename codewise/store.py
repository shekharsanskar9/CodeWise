"""
Persistent project/file metadata (SQLite). Survives restarts, unlike the old in-memory dict.
"""

import sqlite3
from contextlib import closing
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    embed_model TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    chunks      INTEGER NOT NULL,
    size        INTEGER NOT NULL,
    lines       INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    PRIMARY KEY (project_id, filename)
);
"""


class ProjectStore:
    def __init__(self, db_path):
        self.db_path = db_path
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create_project(self, project_id, embed_model, created_at=None):
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO projects (id, created_at, embed_model) VALUES (?, ?, ?)",
                (project_id, created_at or datetime.now().isoformat(), embed_model),
            )

    def get_project(self, project_id):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return dict(row) if row else None

    def upsert_file(self, project_id, filename, chunks, size, lines):
        """Record a file; re-uploading the same path replaces its row instead of double-counting."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO files (project_id, filename, chunks, size, lines, uploaded_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (project_id, filename) DO UPDATE SET
                       chunks = excluded.chunks, size = excluded.size,
                       lines = excluded.lines, uploaded_at = excluded.uploaded_at""",
                (project_id, filename, chunks, size, lines, datetime.now().isoformat()),
            )

    def list_files(self, project_id):
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT filename, chunks, size, lines, uploaded_at FROM files "
                "WHERE project_id = ? ORDER BY filename",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def metadata(self, project_id):
        """Project summary in the shape the API has always returned."""
        project = self.get_project(project_id)
        if not project:
            return None
        files = self.list_files(project_id)
        return {
            'files': files,
            'created_at': project['created_at'],
            'embed_model': project['embed_model'],
            'total_lines': sum(f['lines'] for f in files),
        }
