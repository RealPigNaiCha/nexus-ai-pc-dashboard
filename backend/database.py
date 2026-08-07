from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _highlight_excerpt(content: str, terms: list[str], width: int = 240) -> str:
    folded = content.casefold()
    positions = [folded.find(term.casefold()) for term in terms]
    positions = [position for position in positions if position >= 0]
    start = max((min(positions) if positions else 0) - 72, 0)
    end = min(start + width, len(content))
    excerpt = content[start:end]
    pattern = re.compile("|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True)), re.IGNORECASE)
    highlighted = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", excerpt)
    if start:
        highlighted = f"... {highlighted}"
    if end < len(content):
        highlighted = f"{highlighted} ..."
    return highlighted


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    document_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    location TEXT,
    source TEXT,
    source_path TEXT,
    content_hash TEXT,
    file_size INTEGER,
    indexed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    page_number INTEGER,
    paragraph_number INTEGER,
    content TEXT NOT NULL,
    UNIQUE(document_id, ordinal)
);

CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    content,
    content='document_chunks',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS document_chunks_ai AFTER INSERT ON document_chunks BEGIN
    INSERT INTO document_chunks_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS document_chunks_ad AFTER DELETE ON document_chunks BEGIN
    INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS document_chunks_au AFTER UPDATE ON document_chunks BEGIN
    INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO document_chunks_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS learning_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    goal TEXT NOT NULL,
    target_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    course_id INTEGER REFERENCES learning_courses(id) ON DELETE CASCADE,
    description TEXT,
    mastery REAL NOT NULL DEFAULT 0 CHECK (mastery >= 0 AND mastery <= 100),
    status TEXT NOT NULL DEFAULT 'not_started',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_score REAL,
    due_at TEXT,
    fsrs_card_json TEXT,
    created_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_prerequisites (
    concept_id INTEGER NOT NULL REFERENCES learning_concepts(id) ON DELETE CASCADE,
    prerequisite_id INTEGER NOT NULL REFERENCES learning_concepts(id) ON DELETE CASCADE,
    PRIMARY KEY (concept_id, prerequisite_id),
    CHECK (concept_id != prerequisite_id)
);

CREATE TABLE IF NOT EXISTS learning_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id INTEGER NOT NULL REFERENCES learning_concepts(id),
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    prompt TEXT,
    answer TEXT,
    feedback TEXT,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    duration_seconds INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    hints_used INTEGER NOT NULL DEFAULT 0 CHECK (hints_used >= 0),
    rating INTEGER CHECK (rating IS NULL OR (rating >= 1 AND rating <= 4)),
    review_log_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER REFERENCES learning_courses(id) ON DELETE SET NULL,
    goal TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS research_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    question TEXT NOT NULL,
    research_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES research_projects(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES research_projects(id) ON DELETE SET NULL,
    query TEXT NOT NULL,
    providers_json TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT NOT NULL UNIQUE,
    doi TEXT UNIQUE,
    title TEXT NOT NULL,
    abstract TEXT,
    authors_json TEXT NOT NULL DEFAULT '[]',
    publication_year INTEGER,
    publication_date TEXT,
    venue TEXT,
    paper_type TEXT,
    citation_count INTEGER,
    url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_paper_sources (
    paper_id INTEGER NOT NULL REFERENCES research_papers(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY(provider, external_id)
);

CREATE TABLE IF NOT EXISTS research_search_results (
    search_run_id INTEGER NOT NULL REFERENCES research_search_runs(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES research_papers(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    providers_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY(search_run_id, paper_id)
);

CREATE TABLE IF NOT EXISTS research_screening_decisions (
    project_id INTEGER NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES research_papers(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK(decision IN ('include', 'exclude', 'maybe')),
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, paper_id)
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    run_tests INTEGER NOT NULL DEFAULT 1,
    generate_summary INTEGER NOT NULL DEFAULT 1,
    allow_dependencies INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    task_file TEXT,
    task_sha256 TEXT,
    handoff_requested_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    model TEXT,
    role TEXT,
    source TEXT NOT NULL,
    duration_ms INTEGER NOT NULL CHECK(duration_ms >= 0),
    status TEXT NOT NULL CHECK(status IN ('success', 'error', 'cancelled')),
    error_code TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zotero_syncs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    collection_count INTEGER NOT NULL DEFAULT 0,
    attachment_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS zotero_items (
    key TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    title TEXT,
    year TEXT,
    doi TEXT,
    url TEXT,
    creators_json TEXT NOT NULL DEFAULT '[]',
    collections_json TEXT NOT NULL DEFAULT '[]',
    attachment_paths_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_attempts_concept ON learning_attempts(concept_id);
CREATE INDEX IF NOT EXISTS idx_notes_project ON research_notes(project_id);
CREATE INDEX IF NOT EXISTS idx_research_runs_project ON research_search_runs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_results_run ON research_search_results(search_run_id, rank);
CREATE INDEX IF NOT EXISTS idx_research_results_paper ON research_search_results(paper_id);
CREATE INDEX IF NOT EXISTS idx_research_screening_project ON research_screening_decisions(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_calls_created ON model_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_zotero_syncs_created ON zotero_syncs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_zotero_items_type ON zotero_items(item_type);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)
            self._seed(connection)
            connection.commit()

    def health(self) -> bool:
        try:
            with self.connect() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    def query_all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            return [dict(row) for row in rows]

    def query_one(self, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(sql, parameters).fetchone()
            return dict(row) if row else None

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> int:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(sql, parameters)
            connection.commit()
            return int(cursor.lastrowid)

    def execute_many(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        with self._write_lock, self.connect() as connection:
            connection.executemany(sql, rows)
            connection.commit()

    def claim_agent_handoff(self, task_id: int) -> dict[str, Any] | None:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET status = 'handoff_pending', updated_at = ?, last_error = NULL
                WHERE id = ? AND status = 'queued'
                """,
                (now, task_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
            connection.commit()
            return dict(row) if row else None

    def complete_agent_handoff(
        self,
        task_id: int,
        *,
        task_file: str,
        task_sha256: str,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET status = 'handoff_requested', task_file = ?, task_sha256 = ?,
                    handoff_requested_at = ?, updated_at = ?, last_error = NULL
                WHERE id = ? AND status = 'handoff_pending'
                """,
                (task_file, task_sha256, now, now, task_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
            connection.commit()
            return dict(row) if row else None

    def fail_agent_handoff(self, task_id: int, error_code: str) -> dict[str, Any] | None:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_tasks
                SET status = 'handoff_failed', updated_at = ?, last_error = ?
                WHERE id = ? AND status = 'handoff_pending'
                """,
                (now, error_code[:100], task_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
            connection.commit()
            return dict(row) if row else None

    def save_research_search(
        self,
        *,
        project_id: int,
        query: str,
        providers: list[str],
        papers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist one fully fetched literature search as a single transaction."""
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            if not connection.execute(
                "SELECT id FROM research_projects WHERE id = ?",
                (project_id,),
            ).fetchone():
                raise LookupError("Project not found")

            cursor = connection.execute(
                """
                INSERT INTO research_search_runs(
                    project_id, query, providers_json, result_count, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    query,
                    json.dumps(providers, ensure_ascii=False, separators=(",", ":")),
                    len(papers),
                    now,
                ),
            )
            search_run_id = int(cursor.lastrowid)

            for rank, paper in enumerate(papers, start=1):
                paper_id = self._upsert_research_paper(connection, paper, now)
                connection.execute(
                    """
                    INSERT INTO research_search_results(
                        search_run_id, paper_id, rank, providers_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        search_run_id,
                        paper_id,
                        rank,
                        json.dumps(paper["providers"], ensure_ascii=False, separators=(",", ":")),
                    ),
                )

            connection.commit()
            return self._research_search_details(connection, search_run_id) or {}

    def get_research_search(self, search_run_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            return self._research_search_details(connection, search_run_id)

    def list_research_searches(self, project_id: int, limit: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_search_runs
                WHERE project_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
            return [self._decode_research_run(dict(row)) for row in rows]

    def save_screening_decision(
        self,
        *,
        project_id: int,
        paper_id: int,
        decision: str,
        reason: str | None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            if not connection.execute(
                "SELECT id FROM research_projects WHERE id = ?",
                (project_id,),
            ).fetchone():
                raise LookupError("Project not found")
            in_project = connection.execute(
                """
                SELECT 1
                FROM research_search_results AS result
                JOIN research_search_runs AS run ON run.id = result.search_run_id
                WHERE run.project_id = ? AND result.paper_id = ?
                LIMIT 1
                """,
                (project_id, paper_id),
            ).fetchone()
            if not in_project:
                raise LookupError("Paper not found in project")
            connection.execute(
                """
                INSERT INTO research_screening_decisions(
                    project_id, paper_id, decision, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, paper_id) DO UPDATE SET
                    decision = excluded.decision,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (project_id, paper_id, decision, reason, now, now),
            )
            connection.commit()
            row = connection.execute(
                """
                SELECT decision.*, paper.doi, paper.title
                FROM research_screening_decisions AS decision
                JOIN research_papers AS paper ON paper.id = decision.paper_id
                WHERE decision.project_id = ? AND decision.paper_id = ?
                """,
                (project_id, paper_id),
            ).fetchone()
            return dict(row)

    def list_screening_decisions(self, project_id: int) -> list[dict[str, Any]]:
        return self.query_all(
            """
            SELECT decision.*, paper.doi, paper.title, paper.url
            FROM research_screening_decisions AS decision
            JOIN research_papers AS paper ON paper.id = decision.paper_id
            WHERE decision.project_id = ?
            ORDER BY decision.updated_at DESC, decision.paper_id
            """,
            (project_id,),
        )

    @staticmethod
    def _upsert_research_paper(
        connection: sqlite3.Connection,
        paper: dict[str, Any],
        now: str,
    ) -> int:
        canonical_key = str(paper["canonical_key"])
        doi = paper.get("doi")
        source_ids = paper.get("source_ids")
        if not isinstance(source_ids, dict) or not source_ids:
            raise ValueError("Research paper requires source identifiers")

        existing_ids: set[int] = set()
        row = connection.execute(
            "SELECT id FROM research_papers WHERE canonical_key = ? OR (? IS NOT NULL AND doi = ?)",
            (canonical_key, doi, doi),
        ).fetchone()
        if row:
            existing_ids.add(int(row["id"]))
        for provider, external_id in source_ids.items():
            source = connection.execute(
                """
                SELECT paper_id FROM research_paper_sources
                WHERE provider = ? AND external_id = ?
                """,
                (provider, external_id),
            ).fetchone()
            if source:
                existing_ids.add(int(source["paper_id"]))
        if len(existing_ids) > 1:
            raise ValueError("Conflicting research paper identifiers")

        authors = [
            author.strip()
            for author in paper.get("authors", [])
            if isinstance(author, str) and author.strip()
        ]
        if existing_ids:
            paper_id = existing_ids.pop()
            existing = connection.execute(
                "SELECT * FROM research_papers WHERE id = ?",
                (paper_id,),
            ).fetchone()
            previous_authors = json.loads(existing["authors_json"] or "[]")
            authors = list(dict.fromkeys([*previous_authors, *authors]))
            connection.execute(
                """
                UPDATE research_papers SET
                    canonical_key = CASE WHEN doi IS NULL AND ? IS NOT NULL THEN ? ELSE canonical_key END,
                    doi = COALESCE(doi, ?),
                    title = CASE WHEN LENGTH(?) > LENGTH(title) THEN ? ELSE title END,
                    abstract = CASE
                        WHEN abstract IS NULL OR LENGTH(COALESCE(?, '')) > LENGTH(abstract) THEN ?
                        ELSE abstract
                    END,
                    authors_json = ?,
                    publication_year = COALESCE(publication_year, ?),
                    publication_date = COALESCE(publication_date, ?),
                    venue = COALESCE(venue, ?),
                    paper_type = COALESCE(paper_type, ?),
                    citation_count = CASE
                        WHEN ? IS NULL THEN citation_count
                        WHEN citation_count IS NULL OR ? > citation_count THEN ?
                        ELSE citation_count
                    END,
                    url = COALESCE(url, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    doi,
                    canonical_key,
                    doi,
                    paper["title"],
                    paper["title"],
                    paper.get("abstract"),
                    paper.get("abstract"),
                    json.dumps(authors, ensure_ascii=False, separators=(",", ":")),
                    paper.get("publication_year"),
                    paper.get("publication_date"),
                    paper.get("venue"),
                    paper.get("paper_type"),
                    paper.get("citation_count"),
                    paper.get("citation_count"),
                    paper.get("citation_count"),
                    paper.get("url"),
                    now,
                    paper_id,
                ),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO research_papers(
                    canonical_key, doi, title, abstract, authors_json,
                    publication_year, publication_date, venue, paper_type,
                    citation_count, url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_key,
                    doi,
                    paper["title"],
                    paper.get("abstract"),
                    json.dumps(authors, ensure_ascii=False, separators=(",", ":")),
                    paper.get("publication_year"),
                    paper.get("publication_date"),
                    paper.get("venue"),
                    paper.get("paper_type"),
                    paper.get("citation_count"),
                    paper.get("url"),
                    now,
                    now,
                ),
            )
            paper_id = int(cursor.lastrowid)

        for provider, external_id in source_ids.items():
            connection.execute(
                """
                INSERT INTO research_paper_sources(
                    paper_id, provider, external_id, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, external_id) DO UPDATE SET
                    paper_id = excluded.paper_id,
                    last_seen_at = excluded.last_seen_at
                """,
                (paper_id, provider, external_id, now, now),
            )
        return paper_id

    @classmethod
    def _research_search_details(
        cls,
        connection: sqlite3.Connection,
        search_run_id: int,
    ) -> dict[str, Any] | None:
        run = connection.execute(
            "SELECT * FROM research_search_runs WHERE id = ?",
            (search_run_id,),
        ).fetchone()
        if not run:
            return None
        rows = connection.execute(
            """
            SELECT
                paper.*, result.rank, result.providers_json,
                decision.decision AS screening_decision,
                decision.reason AS screening_reason
            FROM research_search_results AS result
            JOIN research_papers AS paper ON paper.id = result.paper_id
            JOIN research_search_runs AS search ON search.id = result.search_run_id
            LEFT JOIN research_screening_decisions AS decision
                ON decision.project_id = search.project_id AND decision.paper_id = paper.id
            WHERE result.search_run_id = ?
            ORDER BY result.rank
            """,
            (search_run_id,),
        ).fetchall()
        return {
            "search": cls._decode_research_run(dict(run)),
            "papers": [cls._decode_research_paper(dict(row)) for row in rows],
        }

    @staticmethod
    def _decode_research_run(run: dict[str, Any]) -> dict[str, Any]:
        run["providers"] = json.loads(run.pop("providers_json"))
        return run

    @staticmethod
    def _decode_research_paper(paper: dict[str, Any]) -> dict[str, Any]:
        paper["authors"] = json.loads(paper.pop("authors_json"))
        paper["providers"] = json.loads(paper.pop("providers_json"))
        paper.pop("canonical_key", None)
        return paper

    def create_learning_concept(
        self,
        *,
        course_id: int,
        name: str,
        description: str | None,
        prerequisite_ids: list[int],
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            if not connection.execute("SELECT id FROM learning_courses WHERE id = ?", (course_id,)).fetchone():
                raise LookupError("Course not found")
            if prerequisite_ids:
                placeholders = ",".join("?" for _ in prerequisite_ids)
                found = connection.execute(
                    f"SELECT COUNT(*) FROM learning_concepts WHERE course_id = ? AND id IN ({placeholders})",
                    (course_id, *prerequisite_ids),
                ).fetchone()[0]
                if found != len(set(prerequisite_ids)):
                    raise LookupError("Prerequisite not found in course")
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO learning_concepts(
                        course_id, name, description, mastery, status, attempt_count,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 0, 'not_started', 0, ?, ?)
                    """,
                    (course_id, name, description, now, now),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("Concept name already exists") from error
            concept_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO learning_prerequisites(concept_id, prerequisite_id) VALUES (?, ?)",
                [(concept_id, prerequisite_id) for prerequisite_id in dict.fromkeys(prerequisite_ids)],
            )
            connection.commit()
            row = connection.execute("SELECT * FROM learning_concepts WHERE id = ?", (concept_id,)).fetchone()
            return dict(row)

    def create_learning_course(
        self,
        *,
        title: str,
        goal: str,
        target_date: str | None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO learning_courses(title, goal, target_date, status, created_at, updated_at)
                    VALUES (?, ?, ?, 'active', ?, ?)
                    """,
                    (title, goal, target_date, now, now),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("Course title already exists") from error
            connection.commit()
            row = connection.execute("SELECT * FROM learning_courses WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return dict(row)

    def record_learning_review(
        self,
        *,
        concept_id: int,
        score: float,
        prompt: str | None,
        answer: str | None,
        feedback: str | None,
        confidence: float | None,
        duration_seconds: int | None,
        hints_used: int,
        mastery: float,
        status: str,
        rating: int,
        due_at: str,
        card_json: str,
        review_log_json: str,
    ) -> tuple[int, dict[str, Any]]:
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            if not connection.execute("SELECT id FROM learning_concepts WHERE id = ?", (concept_id,)).fetchone():
                raise LookupError("Concept not found")
            cursor = connection.execute(
                """
                INSERT INTO learning_attempts(
                    concept_id, score, prompt, answer, feedback, confidence,
                    duration_seconds, hints_used, rating, review_log_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    concept_id,
                    score,
                    prompt,
                    answer,
                    feedback,
                    confidence,
                    duration_seconds,
                    hints_used,
                    rating,
                    review_log_json,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE learning_concepts
                SET mastery = ?, status = ?, attempt_count = attempt_count + 1,
                    last_score = ?, due_at = ?, fsrs_card_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (mastery, status, score, due_at, card_json, now, concept_id),
            )
            connection.commit()
            concept = connection.execute("SELECT * FROM learning_concepts WHERE id = ?", (concept_id,)).fetchone()
            return int(cursor.lastrowid), dict(concept)

    def audit(self, category: str, action: str, target: str | None, result: str = "success") -> None:
        self.execute(
            "INSERT INTO audit_events(category, action, target, result, created_at) VALUES (?, ?, ?, ?, ?)",
            (category, action, target, result, utc_now()),
        )

    def record_model_call(
        self,
        *,
        provider: str,
        operation: str,
        source: str,
        duration_ms: int,
        status: str,
        model: str | None = None,
        role: str | None = None,
        error_code: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        self.execute(
            """
            INSERT INTO model_calls(
                provider, operation, model, role, source, duration_ms, status, error_code,
                prompt_tokens, completion_tokens, total_tokens, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                operation,
                model,
                role,
                source,
                max(0, duration_ms),
                status,
                error_code,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                utc_now(),
            ),
        )

    def quick_check(self) -> str:
        with self.connect() as connection:
            return str(connection.execute("PRAGMA quick_check").fetchone()[0])

    def backup_to(self, destination: Path) -> Path:
        """Create an online SQLite backup using the native backup API."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self.connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
        return destination

    @staticmethod
    def verify_backup(path: Path) -> str:
        with sqlite3.connect(path) as connection:
            return str(connection.execute("PRAGMA quick_check").fetchone()[0])

    def save_zotero_sync(
        self,
        *,
        items: list[dict[str, Any]],
        collection_count: int,
        attachment_count: int,
        status: str = "success",
        error: str | None = None,
        replace_items: bool = True,
    ) -> dict[str, Any]:
        """Replace the Zotero snapshot in a single transaction."""
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            if replace_items:
                connection.execute("DELETE FROM zotero_items")
                connection.executemany(
                    """
                    INSERT INTO zotero_items(
                        key, item_type, title, year, doi, url, creators_json,
                        collections_json, attachment_paths_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item["key"],
                            item["item_type"],
                            item.get("title"),
                            item.get("year"),
                            item.get("doi"),
                            item.get("url"),
                            json.dumps(item.get("creators", []), ensure_ascii=False),
                            json.dumps(item.get("collections", []), ensure_ascii=False),
                            json.dumps(item.get("attachment_paths", []), ensure_ascii=False),
                            now,
                        )
                        for item in items
                    ],
                )
            cursor = connection.execute(
                """
                INSERT INTO zotero_syncs(
                    status, item_count, collection_count, attachment_count, error,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (status, len(items), collection_count, attachment_count, error, now, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM zotero_syncs WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return dict(row)

    def get_zotero_status(self) -> dict[str, Any]:
        last_sync = self.query_one(
            "SELECT * FROM zotero_syncs ORDER BY id DESC LIMIT 1"
        )
        item_count = int(
            self.query_one("SELECT COUNT(*) AS count FROM zotero_items")["count"]
        )
        return {
            "last_sync": last_sync,
            "item_count": item_count,
        }

    def get_model_roles(self) -> list[dict[str, str]]:
        rows = self.query_all(
            "SELECT key, value FROM settings WHERE key LIKE 'model_role.%' ORDER BY key"
        )
        roles: dict[str, dict[str, str]] = {}
        for row in rows:
            key = row["key"]
            if not key.startswith("model_role."):
                continue
            role, _, field = key[len("model_role.") :].partition(".")
            if not role or not field:
                continue
            roles.setdefault(role, {})[field] = row["value"]
        return [
            {
                "role": role,
                "provider": fields.get("provider", ""),
                "model": fields.get("model", ""),
                "endpoint": fields.get("endpoint", ""),
            }
            for role, fields in sorted(roles.items())
        ]

    def save_model_role(self, *, role: str, provider: str, model: str, endpoint: str) -> None:
        now = utc_now()
        self.execute_many(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            [
                (f"model_role.{role}.provider", provider, now),
                (f"model_role.{role}.model", model, now),
                (f"model_role.{role}.endpoint", endpoint, now),
            ],
        )

    def import_document(
        self,
        *,
        title: str,
        document_type: str,
        source_path: str,
        content_hash: str,
        file_size: int,
        chunks: list[tuple[int, int | None, int | None, str]],
    ) -> tuple[dict[str, Any], int, bool]:
        """Insert or replace an indexed document and its chunks atomically."""
        now = utc_now()
        with self._write_lock, self.connect() as connection:
            existing_path = connection.execute(
                "SELECT * FROM documents WHERE source_path = ?",
                (source_path,),
            ).fetchone()
            if existing_path and existing_path["content_hash"] == content_hash:
                chunk_count = connection.execute(
                    "SELECT COUNT(*) FROM document_chunks WHERE document_id = ?",
                    (existing_path["id"],),
                ).fetchone()[0]
                return dict(existing_path), int(chunk_count), False

            existing_hash = connection.execute(
                "SELECT * FROM documents WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if existing_path and existing_hash and existing_path["id"] != existing_hash["id"]:
                connection.execute("DELETE FROM documents WHERE id = ?", (existing_path["id"],))
                connection.commit()
                chunk_count = connection.execute(
                    "SELECT COUNT(*) FROM document_chunks WHERE document_id = ?",
                    (existing_hash["id"],),
                ).fetchone()[0]
                return dict(existing_hash), int(chunk_count), True

            if existing_path:
                document_id = int(existing_path["id"])
                connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
                connection.execute(
                    """
                    UPDATE documents
                    SET title = ?, document_type = ?, status = 'ready', location = ?,
                        source_path = ?, content_hash = ?, file_size = ?, indexed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        document_type,
                        source_path,
                        source_path,
                        content_hash,
                        file_size,
                        now,
                        now,
                        document_id,
                    ),
                )
            elif existing_hash:
                chunk_count = connection.execute(
                    "SELECT COUNT(*) FROM document_chunks WHERE document_id = ?",
                    (existing_hash["id"],),
                ).fetchone()[0]
                return dict(existing_hash), int(chunk_count), False
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO documents(
                        title, document_type, status, location, source_path, content_hash,
                        file_size, indexed_at, created_at, updated_at
                    )
                    VALUES (?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        title,
                        document_type,
                        source_path,
                        source_path,
                        content_hash,
                        file_size,
                        now,
                        now,
                        now,
                    ),
                )
                document_id = int(cursor.lastrowid)

            connection.executemany(
                """
                INSERT INTO document_chunks(document_id, ordinal, page_number, paragraph_number, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (document_id, ordinal, page_number, paragraph_number, content)
                    for ordinal, page_number, paragraph_number, content in chunks
                ],
            )
            connection.commit()
            document = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            return dict(document), len(chunks), True

    def search_document_chunks(self, query: str, limit: int) -> list[dict[str, Any]]:
        terms = re.findall(
            r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[^\W_]+",
            query,
            flags=re.UNICODE,
        )
        if not terms:
            return []
        if any(CJK_PATTERN.search(term) or len(term) < 3 for term in terms):
            return self._search_document_chunks_like(terms, limit)

        match_query = " AND ".join(f'"{term}"' for term in terms)
        results = self.query_all(
            """
            SELECT
                d.id AS document_id,
                d.title,
                d.document_type,
                d.source_path,
                c.page_number AS page,
                c.paragraph_number AS paragraph,
                c.ordinal AS chunk_index,
                c.content AS chunk,
                snippet(document_chunks_fts, 0, '<mark>', '</mark>', ' ... ', 24) AS snippet
            FROM document_chunks_fts
            JOIN document_chunks AS c ON c.id = document_chunks_fts.rowid
            JOIN documents AS d ON d.id = c.document_id
            WHERE document_chunks_fts MATCH ?
            ORDER BY bm25(document_chunks_fts), d.id, c.ordinal
            LIMIT ?
            """,
            (match_query, limit),
        )
        if len(results) >= limit:
            return results

        seen = {(result["document_id"], result["chunk_index"]) for result in results}
        for result in self._search_document_chunks_like(terms, limit):
            key = (result["document_id"], result["chunk_index"])
            if key not in seen:
                results.append(result)
                seen.add(key)
            if len(results) >= limit:
                break
        return results

    def _search_document_chunks_like(self, terms: list[str], limit: int) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: list[Any] = []
        for term in terms:
            pattern = f"%{term}%"
            conditions.append("(c.content LIKE ? OR (d.title LIKE ? AND c.ordinal = 0))")
            parameters.extend([pattern, pattern])
        parameters.append(limit)
        results = self.query_all(
            f"""
            SELECT
                d.id AS document_id,
                d.title,
                d.document_type,
                d.source_path,
                c.page_number AS page,
                c.paragraph_number AS paragraph,
                c.ordinal AS chunk_index,
                c.content AS chunk,
                c.content AS snippet
            FROM document_chunks AS c
            JOIN documents AS d ON d.id = c.document_id
            WHERE {' AND '.join(conditions)}
            ORDER BY d.id, c.ordinal
            LIMIT ?
            """,
            tuple(parameters),
        )
        for result in results:
            result["snippet"] = _highlight_excerpt(result["chunk"], terms)
        return results

    def _migrate(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)")}
        additions = {
            "source_path": "TEXT",
            "content_hash": "TEXT",
            "file_size": "INTEGER",
            "indexed_at": "TEXT",
        }
        for name, data_type in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE documents ADD COLUMN {name} {data_type}")

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source_path
            ON documents(source_path) WHERE source_path IS NOT NULL
            """
        )

        learning_columns = {row["name"] for row in connection.execute("PRAGMA table_info(learning_concepts)")}
        learning_additions = {
            "course_id": "INTEGER REFERENCES learning_courses(id) ON DELETE CASCADE",
            "description": "TEXT",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "last_score": "REAL",
            "due_at": "TEXT",
            "fsrs_card_json": "TEXT",
            "created_at": "TEXT",
        }
        for name, definition in learning_additions.items():
            if name not in learning_columns:
                connection.execute(f"ALTER TABLE learning_concepts ADD COLUMN {name} {definition}")

        attempt_columns = {row["name"] for row in connection.execute("PRAGMA table_info(learning_attempts)")}
        attempt_additions = {
            "answer": "TEXT",
            "feedback": "TEXT",
            "confidence": "REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))",
            "duration_seconds": "INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0)",
            "hints_used": "INTEGER NOT NULL DEFAULT 0 CHECK (hints_used >= 0)",
            "rating": "INTEGER CHECK (rating IS NULL OR (rating >= 1 AND rating <= 4))",
            "review_log_json": "TEXT",
        }
        for name, definition in attempt_additions.items():
            if name not in attempt_columns:
                connection.execute(f"ALTER TABLE learning_attempts ADD COLUMN {name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_concepts_course ON learning_concepts(course_id, due_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_learning_due ON learning_concepts(due_at, mastery)"
        )
        agent_columns = {row["name"] for row in connection.execute("PRAGMA table_info(agent_tasks)")}
        agent_additions = {
            "updated_at": "TEXT",
            "task_file": "TEXT",
            "task_sha256": "TEXT",
            "handoff_requested_at": "TEXT",
            "last_error": "TEXT",
        }
        for name, definition in agent_additions.items():
            if name not in agent_columns:
                connection.execute(f"ALTER TABLE agent_tasks ADD COLUMN {name} {definition}")
        connection.execute(
            "UPDATE agent_tasks SET updated_at = created_at WHERE updated_at IS NULL"
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_content_hash
            ON documents(content_hash) WHERE content_hash IS NOT NULL
            """
        )

        model_columns = {row["name"] for row in connection.execute("PRAGMA table_info(model_calls)")}
        model_additions = {
            "role": "TEXT",
            "prompt_tokens": "INTEGER",
            "completion_tokens": "INTEGER",
            "total_tokens": "INTEGER",
        }
        for name, definition in model_additions.items():
            if name not in model_columns:
                connection.execute(f"ALTER TABLE model_calls ADD COLUMN {name} {definition}")

        migration_now = utc_now()
        connection.executemany(
            """
            INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            """,
            [
                ("model_role.reasoning.provider", "openai", migration_now),
                ("model_role.reasoning.model", "", migration_now),
                ("model_role.reasoning.endpoint", "https://api.openai.com/v1", migration_now),
                ("model_role.fast.provider", "openai", migration_now),
                ("model_role.fast.model", "", migration_now),
                ("model_role.fast.endpoint", "https://api.openai.com/v1", migration_now),
                ("model_role.vision.provider", "openai", migration_now),
                ("model_role.vision.model", "", migration_now),
                ("model_role.vision.endpoint", "https://api.openai.com/v1", migration_now),
                ("ops.backup.enabled", "1", migration_now),
                ("ops.backup.interval_hours", "24", migration_now),
                ("ops.backup.keep_count", "14", migration_now),
            ],
        )

    def _seed(self, connection: sqlite3.Connection) -> None:
        now = utc_now()
        if connection.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                [
                    ("provider", "OpenAI", now),
                    ("endpoint", "https://api.openai.com/v1", now),
                    ("data_path", r"C:\AI-PC", now),
                ],
            )
