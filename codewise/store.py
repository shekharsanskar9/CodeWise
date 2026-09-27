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
CREATE TABLE IF NOT EXISTS symbols (
    project_id  TEXT NOT NULL,
    path        TEXT NOT NULL,
    name        TEXT NOT NULL,
    qualname    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS symbols_name ON symbols (project_id, name);
CREATE INDEX IF NOT EXISTS symbols_path ON symbols (project_id, path);
CREATE TABLE IF NOT EXISTS calls (
    project_id  TEXT NOT NULL,
    path        TEXT NOT NULL,
    line        INTEGER NOT NULL,
    name        TEXT NOT NULL,
    caller      TEXT NOT NULL,
    expr        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS calls_name ON calls (project_id, name);
CREATE INDEX IF NOT EXISTS calls_caller ON calls (project_id, caller);
CREATE INDEX IF NOT EXISTS calls_path ON calls (project_id, path);
CREATE TABLE IF NOT EXISTS imports (
    project_id  TEXT NOT NULL,
    path        TEXT NOT NULL,
    line        INTEGER NOT NULL,
    module      TEXT NOT NULL,
    name        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS imports_path ON imports (project_id, path);
"""

# Stop answers from being flooded by very common names.
GRAPH_ROW_LIMIT = 200


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

    # --- code graph -------------------------------------------------------------------

    def replace_file_graph(self, project_id, path, graph):
        with closing(self._connect()) as conn, conn:
            for table in ('symbols', 'calls', 'imports'):
                conn.execute(f"DELETE FROM {table} WHERE project_id = ? AND path = ?", (project_id, path))
            conn.executemany(
                "INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(project_id, path, d.name, d.qualname, d.kind, d.start_line, d.end_line)
                 for d in graph.definitions])
            conn.executemany(
                "INSERT INTO calls VALUES (?, ?, ?, ?, ?, ?)",
                [(project_id, path, c.line, c.name, c.caller, c.expr) for c in graph.calls])
            conn.executemany(
                "INSERT INTO imports VALUES (?, ?, ?, ?, ?)",
                [(project_id, path, i.line, i.module, i.name) for i in graph.imports])

    def _rows(self, sql, params):
        with closing(self._connect()) as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def find_definitions(self, project_id, name):
        """Definitions whose simple name or qualified name matches (``save`` or ``Store.save``)."""
        return self._rows(
            "SELECT path, name, qualname, kind, start_line, end_line FROM symbols "
            "WHERE project_id = ? AND (name = ? OR qualname = ?) ORDER BY path, start_line LIMIT ?",
            (project_id, name, name, GRAPH_ROW_LIMIT))

    def known_symbol_names(self, project_id, candidates):
        candidates = list(dict.fromkeys(candidates))[:200]
        if not candidates:
            return set()
        marks = ','.join('?' * len(candidates))
        rows = self._rows(
            f"SELECT DISTINCT name FROM symbols WHERE project_id = ? AND name IN ({marks}) "
            f"UNION SELECT DISTINCT qualname FROM symbols WHERE project_id = ? AND qualname IN ({marks})",
            (project_id, *candidates, project_id, *candidates))
        return {r['name'] for r in rows}

    def find_callers(self, project_id, name):
        return self._rows(
            "SELECT path, line, caller, expr FROM calls WHERE project_id = ? AND name = ? "
            "ORDER BY path, line LIMIT ?",
            (project_id, name, GRAPH_ROW_LIMIT))

    def find_callees(self, project_id, qualname):
        return self._rows(
            "SELECT path, line, name, expr FROM calls WHERE project_id = ? AND caller = ? "
            "ORDER BY line LIMIT ?",
            (project_id, qualname, GRAPH_ROW_LIMIT))

    def find_name_importers(self, project_id, name):
        return self._rows(
            "SELECT path, line, module, name FROM imports WHERE project_id = ? AND name = ? "
            "ORDER BY path, line LIMIT ?",
            (project_id, name, GRAPH_ROW_LIMIT))

    def all_imports(self, project_id):
        return self._rows(
            "SELECT path, line, module, name FROM imports WHERE project_id = ? ORDER BY path, line",
            (project_id,))

    def file_symbols(self, project_id, path):
        return self._rows(
            "SELECT name, qualname, kind, start_line, end_line FROM symbols "
            "WHERE project_id = ? AND path = ? ORDER BY start_line",
            (project_id, path))
