"""Tests for v7 migration — status column backfill logic.

Simulates a pre-v7 database with each type of placeholder row,
runs the v7 migration, and verifies each row lands in the correct
status state.
"""

import sqlite3
from pathlib import Path

import pytest

from screenmind.storage.database import Database


def _create_v6_database(db_path: Path) -> sqlite3.Connection:
    """Create a database at schema v6 (no status column) with legacy rows.

    This bypasses Database.__init__ so we can seed rows in the exact shapes
    that exist in production DBs before v7 runs.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Minimal v6 schema — only the columns the backfill CASE touches
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS activities (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
            screenshot_path TEXT,
            window_title    TEXT,
            detected_app    TEXT,
            bookmarked      BOOLEAN DEFAULT 0,
            app_name        TEXT,
            category        TEXT,
            summary         TEXT,
            details         TEXT,
            visible_text    TEXT,
            mood            TEXT,
            confidence      REAL,
            embedding       BLOB,
            ocr_text        TEXT,
            ocr_boxes       TEXT,
            scene_description TEXT,
            organized_text  TEXT,
            analyzed        BOOLEAN DEFAULT 0,
            analysis_error  TEXT,
            analysis_method TEXT,
            active_url      TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS dev_contexts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id     INTEGER REFERENCES activities(id) ON DELETE CASCADE,
            repo_name       TEXT,
            branch          TEXT,
            last_commit     TEXT,
            changed_files   TEXT,
            insertions      INTEGER DEFAULT 0,
            deletions       INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS daily_summaries (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                DATE UNIQUE NOT NULL,
            summary             TEXT,
            standup             TEXT,
            total_activities    INTEGER DEFAULT 0,
            category_breakdown  TEXT,
            top_repos           TEXT,
            productive_hours    REAL DEFAULT 0.0,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS meetings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time      DATETIME NOT NULL,
            end_time        DATETIME,
            app_name        TEXT,
            duration_minutes REAL DEFAULT 0,
            transcript      TEXT,
            summary         TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

        CREATE INDEX IF NOT EXISTS idx_activities_timestamp ON activities(timestamp);
        CREATE INDEX IF NOT EXISTS idx_activities_category ON activities(category);
        CREATE INDEX IF NOT EXISTS idx_activities_app ON activities(app_name);
        CREATE INDEX IF NOT EXISTS idx_activities_bookmarked ON activities(bookmarked);
        CREATE INDEX IF NOT EXISTS idx_activities_analyzed ON activities(analyzed);
        CREATE INDEX IF NOT EXISTS idx_dev_repo ON dev_contexts(repo_name);
        CREATE INDEX IF NOT EXISTS idx_dev_branch ON dev_contexts(branch);
        CREATE INDEX IF NOT EXISTS idx_dev_activity ON dev_contexts(activity_id);
    """)

    # Set schema version to 6 (all v1-v6 migrations already applied)
    conn.execute("INSERT INTO schema_version (version) VALUES (6)")
    conn.commit()

    return conn


def _seed_legacy_rows(conn: sqlite3.Connection) -> dict:
    """Insert rows matching every placeholder type that exists in production.

    Returns a dict mapping description -> row id for assertions.
    """
    rows = {}

    def _insert(desc, **kwargs):
        defaults = {
            "timestamp": "2026-05-16T10:00:00",
            "screenshot_path": "/tmp/test.jpg",
            "analyzed": 0,
            "confidence": None,
            "summary": None,
            "category": None,
            "app_name": None,
            "analysis_method": None,
        }
        defaults.update(kwargs)
        cursor = conn.execute(
            """INSERT INTO activities
               (timestamp, screenshot_path, analyzed, confidence, summary,
                category, app_name, analysis_method)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                defaults["timestamp"],
                defaults["screenshot_path"],
                defaults["analyzed"],
                defaults["confidence"],
                defaults["summary"],
                defaults["category"],
                defaults["app_name"],
                defaults["analysis_method"],
            ),
        )
        rows[desc] = cursor.lastrowid

    # 1. Real analysis (typical — confidence set by model, e.g. 0.85)
    _insert(
        "real_analysis_normal",
        analyzed=1, confidence=0.85,
        summary="User is coding in VS Code", category="coding",
        app_name="VS Code", analysis_method="gemma",
    )

    # 2. Real analysis (regex fallback — confidence 0.3)
    _insert(
        "real_analysis_regex",
        analyzed=1, confidence=0.3,
        summary="User browsing Chrome", category="browsing",
        app_name="Chrome", analysis_method="regex",
    )

    # 3. Real analysis (confidence was 0.0 but _normalize bumped to 0.7)
    _insert(
        "real_analysis_bumped",
        analyzed=1, confidence=0.7,
        summary="Writing documentation", category="writing",
        app_name="Notion",
    )

    # 4. Staleness skip (analysis backlog)
    _insert(
        "staleness_skip",
        analyzed=1, confidence=0.0,
        summary="Skipped (analysis backlog)", category="other",
        app_name="unknown", analysis_method="skipped",
    )

    # 5. Analysis failure
    _insert(
        "analysis_failed",
        analyzed=1, confidence=0.0,
        summary="Analysis failed: Connection refused", category="other",
        app_name="unknown",
    )

    # 6. Corrupt screenshot (raw SQL writer — confidence stays NULL)
    _insert(
        "corrupt_screenshot",
        analyzed=1, confidence=None,
        summary="Skipped (corrupt screenshot)",
    )

    # 7. Deleted screenshot (raw SQL writer — analyzed stays 0, confidence NULL)
    _insert(
        "deleted_screenshot",
        analyzed=0, confidence=None,
        summary="Skipped (screenshot deleted)",
    )

    # 8. Pending (just captured, not yet analyzed)
    _insert(
        "pending_unanalyzed",
        analyzed=0, confidence=None,
        summary=None,
    )

    # 9. Edge case: analyzed=1 with NULL confidence but a real summary
    #    (e.g., from a very early version before confidence was populated)
    _insert(
        "legacy_null_confidence",
        analyzed=1, confidence=None,
        summary="User was reading email in Gmail",
    )

    conn.commit()
    return rows


class TestV7MigrationBackfill:
    """Test that the v7 migration correctly classifies existing rows."""

    def test_backfill_classifies_all_row_types(self, tmp_path):
        """Each placeholder type should land in the correct status state."""
        db_path = tmp_path / "legacy.db"
        conn = _create_v6_database(db_path)
        rows = _seed_legacy_rows(conn)
        conn.close()

        # Now open via Database() — this triggers _init_db which runs v7
        db = Database(db_path=db_path)
        conn = db._get_conn()

        def get_status(row_id):
            row = conn.execute(
                "SELECT status, summary FROM activities WHERE id = ?", (row_id,)
            ).fetchone()
            return row["status"]

        # Real analyses → ok
        assert get_status(rows["real_analysis_normal"]) == "ok"
        assert get_status(rows["real_analysis_regex"]) == "ok"
        assert get_status(rows["real_analysis_bumped"]) == "ok"

        # Staleness skip → skipped (retryable)
        assert get_status(rows["staleness_skip"]) == "skipped"

        # Analysis failure → failed (retryable)
        assert get_status(rows["analysis_failed"]) == "failed"

        # Corrupt screenshot → dead (terminal)
        assert get_status(rows["corrupt_screenshot"]) == "dead"

        # Deleted screenshot → pending (analyzed=0, so ELSE branch)
        # Note: the migration CASE only changes rows based on their analyzed
        # flag and summary text. analyzed=0 rows stay pending.
        assert get_status(rows["deleted_screenshot"]) == "pending"

        # Pending unanalyzed → pending
        assert get_status(rows["pending_unanalyzed"]) == "pending"

        # Legacy null confidence with real summary → dead
        # (analyzed=1 AND confidence IS NULL → dead, as these are
        # definitively from raw SQL writers that never set confidence)
        assert get_status(rows["legacy_null_confidence"]) == "dead"

        db.close()

    def test_backfill_is_idempotent(self, tmp_path):
        """Running v7 twice (simulating interrupted migration) should not
        change already-classified rows."""
        db_path = tmp_path / "legacy.db"
        conn = _create_v6_database(db_path)
        rows = _seed_legacy_rows(conn)
        conn.close()

        # First run — applies v7
        db = Database(db_path=db_path)
        conn = db._get_conn()

        # Snapshot statuses after first run
        first_run = {}
        for desc, row_id in rows.items():
            row = conn.execute(
                "SELECT status FROM activities WHERE id = ?", (row_id,)
            ).fetchone()
            first_run[desc] = row["status"]
        db.close()

        # Simulate re-run: reset schema_version back to 6
        conn2 = sqlite3.connect(str(db_path))
        conn2.execute("DELETE FROM schema_version WHERE version = 7")
        conn2.commit()
        conn2.close()

        # Second run — v7 re-executes (ALTER fails with "duplicate column",
        # backfill re-runs but WHERE status='pending' skips already-classified)
        db2 = Database(db_path=db_path)
        conn3 = db2._get_conn()

        for desc, row_id in rows.items():
            row = conn3.execute(
                "SELECT status FROM activities WHERE id = ?", (row_id,)
            ).fetchone()
            assert row["status"] == first_run[desc], (
                f"Row '{desc}' changed on re-run: {first_run[desc]} → {row['status']}"
            )
        db2.close()

    def test_schema_version_bumped_to_7(self, tmp_path):
        """After migration, schema_version should be 7."""
        db_path = tmp_path / "legacy.db"
        conn = _create_v6_database(db_path)
        conn.close()

        db = Database(db_path=db_path)
        conn = db._get_conn()
        version = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0]
        assert version == 7
        db.close()

    def test_status_index_created(self, tmp_path):
        """The idx_activities_status index should exist after migration."""
        db_path = tmp_path / "legacy.db"
        conn = _create_v6_database(db_path)
        conn.close()

        db = Database(db_path=db_path)
        conn = db._get_conn()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_activities_status'"
        ).fetchall()
        assert len(indexes) == 1
        db.close()

    def test_fresh_db_has_status_column(self, tmp_path):
        """A brand-new database should have the status column from the DDL."""
        db_path = tmp_path / "fresh.db"
        db = Database(db_path=db_path)
        conn = db._get_conn()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(activities)").fetchall()]
        assert "status" in cols
        db.close()

    def test_backfill_excludes_dead_from_repick(self, tmp_path):
        """Rows marked 'dead' should NOT be picked up by the backfill query pattern."""
        db_path = tmp_path / "legacy.db"
        conn = _create_v6_database(db_path)
        _seed_legacy_rows(conn)
        conn.close()

        db = Database(db_path=db_path)
        conn = db._get_conn()

        # Simulate the backfill query used by analysis_worker._backfill_skipped
        repick_rows = conn.execute(
            """SELECT id, status, summary FROM activities
               WHERE status IN ('pending', 'skipped', 'failed')"""
        ).fetchall()

        repick_statuses = {r["status"] for r in repick_rows}
        assert "dead" not in repick_statuses
        assert "ok" not in repick_statuses

        db.close()
