"""Durable SQLite state for local runs.

The store deliberately exposes small operations instead of leaking SQL into the controller. Every
mutating operation emits an event, and event IDs are idempotency keys.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .budget import BudgetSpec
from .evaluator import validate_acceptance
from .models import Attempt, Run, RunStatus, Task, TaskStatus
from .policy import (
    PlanDocument,
    PlanPatch,
    PolicyDecision,
    apply_patch,
    validate_evidence,
    validate_reason,
)
from .routing import RouteDecision

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    workspace TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    runner_pid INTEGER,
    runner_pgid INTEGER,
    current_plan_id TEXT,
    current_plan_version INTEGER,
    route_domain TEXT,
    route_reason TEXT,
    route_confidence REAL,
    solver_profile TEXT,
    evaluator_profile TEXT,
    route_required_capabilities TEXT NOT NULL DEFAULT '[]',
    route_evidence TEXT NOT NULL DEFAULT '[]',
    budget TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    parent_id TEXT REFERENCES tasks(id),
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    result_path TEXT,
    last_error TEXT,
    dependencies TEXT NOT NULL DEFAULT '[]',
    acceptance TEXT,
    input_question TEXT,
    input_options TEXT NOT NULL DEFAULT '[]',
    input_answer_path TEXT,
    plan_task_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_run_state_idx ON tasks(run_id, state, created_at);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    runtime TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    heartbeat_at TEXT,
    error TEXT,
    pid INTEGER,
    pgid INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT REFERENCES tasks(id),
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run_idx ON events(run_id, created_at);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_revisions (
    plan_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    version INTEGER NOT NULL,
    parent_version INTEGER,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(run_id, version)
);
CREATE INDEX IF NOT EXISTS plan_revisions_run_idx ON plan_revisions(run_id, version);
CREATE TABLE IF NOT EXISTS policy_decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id),
    action TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS policy_decisions_run_idx ON policy_decisions(run_id, created_at);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, declaration: str
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_plan_revision_key(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS plan_revisions_plan_idx ON plan_revisions(plan_id, version)"
            )
            # Keep upgrades compatible with the P1 database created before plans and detached
            # process metadata existed. SQLite has no IF NOT EXISTS form for ADD COLUMN.
            self._ensure_column(connection, "runs", "runner_pid", "INTEGER")
            self._ensure_column(connection, "runs", "runner_pgid", "INTEGER")
            self._ensure_column(connection, "runs", "current_plan_id", "TEXT")
            self._ensure_column(connection, "runs", "current_plan_version", "INTEGER")
            self._ensure_column(connection, "runs", "route_domain", "TEXT")
            self._ensure_column(connection, "runs", "route_reason", "TEXT")
            self._ensure_column(connection, "runs", "route_confidence", "REAL")
            self._ensure_column(connection, "runs", "solver_profile", "TEXT")
            self._ensure_column(connection, "runs", "evaluator_profile", "TEXT")
            self._ensure_column(connection, "runs", "route_required_capabilities", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "runs", "route_evidence", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "runs", "budget", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "tasks", "dependencies", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "tasks", "acceptance", "TEXT")
            self._ensure_column(connection, "tasks", "input_question", "TEXT")
            self._ensure_column(connection, "tasks", "input_options", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "tasks", "input_answer_path", "TEXT")
            self._ensure_column(connection, "tasks", "plan_task_id", "TEXT")
            self._ensure_column(connection, "attempts", "pid", "INTEGER")
            self._ensure_column(connection, "attempts", "pgid", "INTEGER")
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (1, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (2, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (3, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (4, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (5, utc_now()),
            )

    @staticmethod
    def _migrate_plan_revision_key(connection: sqlite3.Connection) -> None:
        """Upgrade the first feature-006 table, whose key was plan_id/version.

        Plan IDs are stable within a run but callers may intentionally reuse a plan template in
        another run.  Keying revisions by run/version prevents unrelated runs from colliding while
        retaining the plan ID as an indexed lookup/reference field.
        """
        indexes = connection.execute("PRAGMA index_list(plan_revisions)").fetchall()
        primary_columns: list[str] = []
        for index in indexes:
            if index[2]:  # unique; the autoindex for a PRIMARY KEY is unique
                columns = connection.execute(f"PRAGMA index_info({index[1]})").fetchall()
                primary_columns = [column[2] for column in columns]
                if primary_columns:
                    break
        if primary_columns != ["run_id", "version"]:
            connection.execute("ALTER TABLE plan_revisions RENAME TO plan_revisions_legacy")
            connection.execute(
                """CREATE TABLE plan_revisions (
                    plan_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    version INTEGER NOT NULL,
                    parent_version INTEGER,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, version)
                )"""
            )
            connection.execute(
                "INSERT INTO plan_revisions(plan_id, run_id, version, parent_version, document, created_at) "
                "SELECT plan_id, run_id, version, parent_version, document, created_at FROM plan_revisions_legacy"
            )
            connection.execute("DROP TABLE plan_revisions_legacy")
            connection.execute("CREATE INDEX IF NOT EXISTS plan_revisions_run_idx ON plan_revisions(run_id, version)")
            connection.execute("CREATE INDEX IF NOT EXISTS plan_revisions_plan_idx ON plan_revisions(plan_id, version)")

    def create_run(
        self,
        goal: str,
        workspace: str | Path | None = None,
        tasks: list[dict[str, Any]] | None = None,
        route: RouteDecision | None = None,
    ) -> Run:
        goal = goal.strip()
        if not goal:
            raise ValueError("goal must not be empty")
        run_id = uuid.uuid4().hex
        timestamp = utc_now()
        workspace_path = (
            Path(workspace).expanduser().resolve()
            if workspace is not None
            else (self.database.parent / "runs" / run_id).resolve()
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs(id, goal, status, workspace, created_at, updated_at, route_domain, route_reason, route_confidence, solver_profile, evaluator_profile, route_required_capabilities, route_evidence, budget) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, goal, RunStatus.PENDING.value, str(workspace_path), timestamp, timestamp,
                 route.domain if route else None, route.reason if route else None,
                 route.confidence if route else None, route.solver_profile if route else None,
                 route.evaluator_profile if route else None,
                 json.dumps(list(route.required_capabilities) if route else []),
                 json.dumps(list(route.evidence) if route else []),
                 json.dumps(route.budget.to_dict() if route else BudgetSpec().to_dict())),
            )
            plan_tasks = tasks if tasks is not None else [
                {
                    "id": f"task-{uuid.uuid4().hex[:12]}",
                    "title": "Execute user goal",
                    "prompt": goal,
                    "depends_on": [],
                    "acceptance": None,
                }
            ]
            normalized = self._validate_plan_tasks(plan_tasks)
            existing_ids = {
                row["id"]
                for row in connection.execute(
                    f"SELECT id FROM tasks WHERE id IN ({','.join('?' for _ in normalized)})",
                    [item["id"] for item in normalized],
                ).fetchall()
            }
            id_map: dict[str, str] = {}
            reserved = set(existing_ids)
            for item in normalized:
                candidate = item["id"]
                if candidate in reserved:
                    suffix = 1
                    candidate = f"{run_id[:8]}-{item['id']}"
                    while candidate in reserved:
                        suffix += 1
                        candidate = f"{run_id[:8]}-{item['id']}-{suffix}"
                id_map[item["id"]] = candidate
                reserved.add(candidate)
            normalized = [
                {
                    **item,
                    "id": id_map[item["id"]],
                    "depends_on": [id_map[dependency] for dependency in item["depends_on"]],
                }
                for item in normalized
            ]
            for item in normalized:
                state = TaskStatus.READY.value if not item["depends_on"] else TaskStatus.WAITING.value
                connection.execute(
                    "INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item["id"],
                        run_id,
                        item["title"],
                        item["prompt"],
                        state,
                        json.dumps(item["depends_on"]),
                        item["acceptance"],
                        timestamp,
                        timestamp,
                    ),
                )
            self._append_event(
                connection,
                run_id,
                None,
                "run_created",
                {"goal": goal, "task_count": len(normalized), **({"route": route.to_dict()} if route else {})},
            )
            if route is not None:
                self._append_event(connection, run_id, None, "route_selected", route.to_dict())
            for item in normalized:
                self._append_event(
                    connection,
                    run_id,
                    item["id"],
                    "task_created",
                    {
                        "title": item["title"],
                        "dependencies": item["depends_on"],
                        "acceptance": item["acceptance"],
                    },
                )
        return self.get_run(run_id)  # type: ignore[return-value]

    def create_run_with_plan(
        self, document: PlanDocument, decision: PolicyDecision | None = None, workspace: str | Path | None = None,
        route: RouteDecision | None = None,
    ) -> Run:
        """Create a run, first plan revision, tasks, and decision in one transaction."""
        if document.version != 1 or document.parent_version is not None:
            raise ValueError("a new planned run must start at version 1")
        if decision is not None:
            if decision.action != "execute_plan":
                raise ValueError("a planned run requires an execute_plan decision")
            if (decision.plan_id, decision.plan_version) != (document.plan_id, document.version):
                raise ValueError("execute_plan decision does not reference the supplied plan revision")
        timestamp = utc_now()
        run_id = uuid.uuid4().hex
        workspace_path = Path(workspace).expanduser().resolve() if workspace is not None else (self.database.parent / "runs" / run_id).resolve()
        task_items = [task.to_dict() for task in document.tasks]
        normalized = self._validate_plan_tasks(task_items)
        id_map = {item["id"]: f"{run_id[:8]}-{item['id']}" for item in normalized}
        normalized = [{**item, "id": id_map[item["id"]], "plan_task_id": item["id"], "depends_on": [id_map[dependency] for dependency in item["depends_on"]]} for item in normalized]
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs(id, goal, status, workspace, created_at, updated_at, current_plan_id, current_plan_version, route_domain, route_reason, route_confidence, solver_profile, evaluator_profile, route_required_capabilities, route_evidence, budget) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, document.goal, RunStatus.PENDING.value, str(workspace_path), timestamp, timestamp, document.plan_id, 1,
                 route.domain if route else None, route.reason if route else None, route.confidence if route else None,
                 route.solver_profile if route else None, route.evaluator_profile if route else None,
                 json.dumps(list(route.required_capabilities) if route else []),
                 json.dumps(list(route.evidence) if route else []), json.dumps(route.budget.to_dict() if route else BudgetSpec().to_dict())),
            )
            for item in normalized:
                state = TaskStatus.READY.value if not item["depends_on"] else TaskStatus.WAITING.value
                connection.execute(
                    "INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, plan_task_id, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item["id"], run_id, item["title"], item["prompt"], state, json.dumps(item["depends_on"]), item["acceptance"], item["plan_task_id"], timestamp, timestamp),
                )
            connection.execute(
                "INSERT INTO plan_revisions(plan_id, run_id, version, parent_version, document, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (document.plan_id, run_id, document.version, document.parent_version, json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True), timestamp),
            )
            self._append_event(
                connection,
                run_id,
                None,
                "run_created",
                {"goal": document.goal, "task_count": len(normalized), "plan_id": document.plan_id, **({"route": route.to_dict()} if route else {})},
            )
            if route is not None:
                self._append_event(connection, run_id, None, "route_selected", route.to_dict())
            self._append_event(connection, run_id, None, "plan_created", {"plan_id": document.plan_id, "version": 1})
            for item in normalized:
                self._append_event(connection, run_id, item["id"], "task_created", {"title": item["title"], "dependencies": item["depends_on"], "acceptance": item["acceptance"]})
            if decision is not None:
                self._insert_decision(connection, run_id, decision)
        Path(workspace_path).mkdir(parents=True, exist_ok=True)
        return self.get_run(run_id)  # type: ignore[return-value]

    def attach_plan_to_run(
        self,
        run_id: str,
        document: PlanDocument,
        decision: PolicyDecision | None = None,
    ) -> bool:
        """Promote an intake run to a version-one plan without changing its run ID.

        Conversational intake deliberately starts with one durable compiler task so a clarification
        can pause and resume through the normal input lifecycle.  Once compilation succeeds this
        additive transaction installs the immutable plan revision and generated DAG alongside the
        completed intake task.  It does not alter the existing schema or rewrite prior events.
        """
        if not isinstance(document, PlanDocument):
            raise TypeError("document must be a PlanDocument")
        if document.version != 1 or document.parent_version is not None:
            raise ValueError("an attached plan must start at version 1")
        if decision is not None:
            if decision.action != "execute_plan":
                raise ValueError("an attached plan requires an execute_plan decision")
            if (decision.plan_id, decision.plan_version) != (document.plan_id, document.version):
                raise ValueError("execute_plan decision does not reference the attached plan")
        timestamp = utc_now()
        normalized = self._validate_plan_tasks([task.to_dict() for task in document.tasks])
        with self._connect() as connection:
            run = connection.execute(
                "SELECT current_plan_id, current_plan_version, status FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError(f"unknown run: {run_id}")
            if run["current_plan_id"] is not None:
                if run["current_plan_id"] == document.plan_id and run["current_plan_version"] == 1:
                    return False
                raise ValueError("run already has a plan")
            existing_ids = {
                row["id"]
                for row in connection.execute("SELECT id FROM tasks WHERE run_id = ?", (run_id,)).fetchall()
            }
            id_map: dict[str, str] = {}
            for item in normalized:
                candidate = f"{run_id[:8]}-{item['id']}"
                suffix = 1
                while candidate in existing_ids or candidate in id_map.values():
                    suffix += 1
                    candidate = f"{run_id[:8]}-{item['id']}-{suffix}"
                id_map[item["id"]] = candidate
            connection.execute(
                "UPDATE runs SET current_plan_id = ?, current_plan_version = ?, budget = ?, updated_at = ? WHERE id = ?",
                (document.plan_id, document.version, json.dumps(document.budget.to_dict()), timestamp, run_id),
            )
            connection.execute(
                "INSERT INTO plan_revisions(plan_id, run_id, version, parent_version, document, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    document.plan_id,
                    run_id,
                    document.version,
                    document.parent_version,
                    json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )
            self._append_event(
                connection,
                run_id,
                None,
                "plan_created",
                {"plan_id": document.plan_id, "version": document.version, "source": "conversational_intake"},
            )
            for item in normalized:
                physical_id = id_map[item["id"]]
                dependencies = [id_map[dependency] for dependency in item["depends_on"]]
                state = TaskStatus.READY.value if not dependencies else TaskStatus.WAITING.value
                connection.execute(
                    "INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, plan_task_id, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        physical_id,
                        run_id,
                        item["title"],
                        item["prompt"],
                        state,
                        json.dumps(dependencies),
                        item["acceptance"],
                        item["id"],
                        timestamp,
                        timestamp,
                    ),
                )
                self._append_event(
                    connection,
                    run_id,
                    physical_id,
                    "task_created",
                    {
                        "title": item["title"],
                        "dependencies": dependencies,
                        "acceptance": item["acceptance"],
                        "plan_task_id": item["id"],
                    },
                )
            if decision is not None:
                self._insert_decision(connection, run_id, decision)
        return True

    def _insert_decision(self, connection: sqlite3.Connection, run_id: str | None, decision: PolicyDecision, decision_id: str | None = None) -> str:
        decision_id = decision_id or f"decision-{uuid.uuid4().hex}"
        connection.execute(
            "INSERT OR IGNORE INTO policy_decisions(id, run_id, action, payload, created_at) VALUES(?, ?, ?, ?, ?)",
            (decision_id, run_id, decision.action, json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True), utc_now()),
        )
        if run_id is not None:
            self._append_event(connection, run_id, None, "policy_decision", {"decision_id": decision_id, **decision.to_dict()}, event_id=f"event-{decision_id}")
        return decision_id

    def record_decision(self, decision: PolicyDecision, run_id: str | None = None, decision_id: str | None = None) -> str:
        with self._connect() as connection:
            return self._insert_decision(connection, run_id, decision, decision_id)

    def get_current_plan(self, run_id: str) -> PlanDocument | None:
        with self._connect() as connection:
            row = connection.execute("SELECT current_plan_id, current_plan_version FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None or not row["current_plan_id"] or row["current_plan_version"] is None:
                return None
            revision = connection.execute(
                "SELECT document FROM plan_revisions WHERE run_id = ? AND plan_id = ? AND version = ?",
                (run_id, row["current_plan_id"], row["current_plan_version"]),
            ).fetchone()
        return PlanDocument.from_dict(json.loads(revision["document"])) if revision else None

    def list_plan_revisions(self, run_id: str) -> list[PlanDocument]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document FROM plan_revisions WHERE run_id = ? ORDER BY version", (run_id,)
            ).fetchall()
        return [PlanDocument.from_dict(json.loads(row["document"])) for row in rows]

    def list_decisions(self, run_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute("SELECT id, run_id, action, payload, created_at FROM policy_decisions ORDER BY created_at").fetchall()
            else:
                rows = connection.execute("SELECT id, run_id, action, payload, created_at FROM policy_decisions WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        return [{"id": row["id"], "run_id": row["run_id"], "action": row["action"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]} for row in rows]

    def commit_plan_revision(
        self,
        run_id: str,
        document: PlanDocument,
        reason: str,
        evidence: tuple[str, ...] = (),
        *,
        action: str = "patch_plan",
    ) -> PlanDocument:
        """Commit an already validated revision and synchronize not-yet-run scheduler tasks."""
        reason = validate_reason(reason)
        evidence = validate_evidence(list(evidence))
        with self._connect() as connection:
            run = connection.execute("SELECT current_plan_id, current_plan_version, status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise ValueError(f"unknown run: {run_id}")
            if run["current_plan_id"] != document.plan_id or run["current_plan_version"] != document.parent_version:
                raise ValueError("plan revision parent does not match current version")
            if document.parent_version is None or document.version != document.parent_version + 1:
                raise ValueError("plan revision version must increment the current version by one")
            if run["status"] in {RunStatus.RUNNING.value, RunStatus.AWAITING_INPUT.value, RunStatus.CANCELLED.value}:
                raise ValueError("cannot revise a plan while the run is active")
            existing_rows = connection.execute("SELECT * FROM tasks WHERE run_id = ?", (run_id,)).fetchall()
            existing = {row["plan_task_id"] or row["id"]: row for row in existing_rows}
            desired = {task.id: task for task in document.tasks}
            for task_id, row in existing.items():
                if task_id not in desired:
                    if row["state"] == TaskStatus.SUCCEEDED.value:
                        raise ValueError("completed tasks must remain in a plan revision")
                    if row["state"] not in {TaskStatus.SUPERSEDED.value, TaskStatus.CANCELLED.value}:
                        connection.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (TaskStatus.SUPERSEDED.value, utc_now(), row["id"]))
            for task_id, task in desired.items():
                if task_id in existing:
                    row = existing[task_id]
                    physical_dependencies = [existing[dep]["id"] if dep in existing else f"{run_id[:8]}-{dep}" for dep in task.depends_on]
                    acceptance = json.dumps(task.acceptance, ensure_ascii=False, sort_keys=True) if isinstance(task.acceptance, dict) else task.acceptance
                    if row["state"] == TaskStatus.SUCCEEDED.value:
                        if (row["title"], row["prompt"], row["dependencies"], row["acceptance"]) != (task.title, task.prompt, json.dumps(physical_dependencies), acceptance):
                            raise ValueError("completed task definitions are immutable across revisions")
                    else:
                        state = TaskStatus.READY.value if not task.depends_on else TaskStatus.WAITING.value
                        connection.execute("UPDATE tasks SET title = ?, prompt = ?, state = ?, attempts = 0, result_path = NULL, last_error = NULL, dependencies = ?, acceptance = ?, updated_at = ? WHERE id = ?", (task.title, task.prompt, state, json.dumps(physical_dependencies), acceptance, utc_now(), row["id"]))
                else:
                    state = TaskStatus.READY.value if not task.depends_on else TaskStatus.WAITING.value
                    physical_id = f"{run_id[:8]}-{task_id}"
                    physical_dependencies = [existing[dep]["id"] if dep in existing else f"{run_id[:8]}-{dep}" for dep in task.depends_on]
                    connection.execute("INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, plan_task_id, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (physical_id, run_id, task.title, task.prompt, state, json.dumps(physical_dependencies), json.dumps(task.acceptance, ensure_ascii=False) if isinstance(task.acceptance, dict) else task.acceptance, task_id, utc_now(), utc_now()))
            connection.execute("INSERT INTO plan_revisions(plan_id, run_id, version, parent_version, document, created_at) VALUES(?, ?, ?, ?, ?, ?)", (document.plan_id, run_id, document.version, document.parent_version, json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True), utc_now()))
            connection.execute("UPDATE runs SET current_plan_id = ?, current_plan_version = ?, budget = ?, updated_at = ? WHERE id = ?", (document.plan_id, document.version, json.dumps(document.budget.to_dict()), utc_now(), run_id))
            connection.execute("UPDATE runs SET status = ?, updated_at = ? WHERE id = ?", (RunStatus.PENDING.value, utc_now(), run_id))
            self._append_event(connection, run_id, None, "plan_revision_created", {"plan_id": document.plan_id, "version": document.version, "parent_version": document.parent_version, "reason": reason, "evidence": list(evidence)})
            self._insert_decision(
                connection,
                run_id,
                PolicyDecision(
                    action,  # type: ignore[arg-type]
                    reason,
                    1.0,
                    plan_id=document.plan_id,
                    plan_version=document.version,
                    evidence=evidence,
                ),
            )
        return document

    def patch_plan(self, run_id: str, patch: PlanPatch) -> PlanDocument:
        current = self.get_current_plan(run_id)
        if current is None:
            raise ValueError("run has no current plan")
        document = apply_patch(current, patch)
        return self.commit_plan_revision(run_id, document, patch.reason, patch.evidence, action="patch_plan")

    @staticmethod
    def _validate_plan_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not tasks:
            raise ValueError("plan must contain at least one task")
        normalized: list[dict[str, Any]] = []
        ids: set[str] = set()
        for index, raw in enumerate(tasks):
            if not isinstance(raw, dict):
                raise TypeError(f"plan task {index} must be an object")
            task_id = str(raw.get("id", "")).strip()
            title = str(raw.get("title", task_id)).strip()
            prompt = str(raw.get("prompt", "")).strip()
            if not task_id or not prompt:
                raise ValueError(f"plan task {index} requires non-empty id and prompt")
            if task_id in {".", ".."} or Path(task_id).name != task_id or "\\" in task_id:
                raise ValueError(f"plan task id is not a safe path segment: {task_id!r}")
            if task_id in ids:
                raise ValueError(f"plan contains duplicate task id: {task_id}")
            ids.add(task_id)
            dependencies = raw.get("depends_on", raw.get("dependencies", []))
            if dependencies is None:
                dependencies = []
            if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
                raise ValueError(f"dependencies for task {task_id} must be a string array")
            dependencies = [dep.strip() for dep in dependencies]
            if any(not dep for dep in dependencies):
                raise ValueError(f"dependencies for task {task_id} cannot contain empty IDs")
            acceptance = raw.get("acceptance")
            if acceptance is not None and not isinstance(acceptance, (str, dict)):
                raise ValueError(f"acceptance for task {task_id} must be a string or object")
            validate_acceptance(acceptance)
            normalized.append(
                {
                    "id": task_id,
                    "title": title or task_id,
                    "prompt": prompt,
                    "depends_on": dependencies,
                    "acceptance": json.dumps(acceptance, ensure_ascii=False, sort_keys=True)
                    if isinstance(acceptance, dict)
                    else acceptance,
                }
            )
        for item in normalized:
            unknown = set(item["depends_on"]) - ids
            if unknown:
                raise ValueError(
                    f"task {item['id']} references unknown dependencies: {', '.join(sorted(unknown))}"
                )
            if item["id"] in item["depends_on"]:
                raise ValueError(f"task {item['id']} cannot depend on itself")
        graph = {item["id"]: item["depends_on"] for item in normalized}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("plan dependencies contain a cycle")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
        return normalized

    def get_run(self, run_id: str) -> Run | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run(
            id=row["id"],
            goal=row["goal"],
            status=RunStatus(row["status"]),
            workspace=Path(row["workspace"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            runner_pid=row["runner_pid"],
            runner_pgid=row["runner_pgid"],
            current_plan_id=row["current_plan_id"],
            current_plan_version=row["current_plan_version"],
            route_domain=row["route_domain"],
            route_reason=row["route_reason"],
            route_confidence=row["route_confidence"],
            solver_profile=row["solver_profile"],
            evaluator_profile=row["evaluator_profile"],
            route_required_capabilities=tuple(json.loads(row["route_required_capabilities"] or "[]")),
            route_evidence=tuple(json.loads(row["route_evidence"] or "[]")),
            budget=BudgetSpec.from_dict(json.loads(row["budget"] or "{}")),
        )

    def get_task(self, task_id: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self, run_id: str) -> list[Task]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE run_id = ? ORDER BY created_at, id", (run_id,)
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def set_runner_process(self, run_id: str, pid: int | None, pgid: int | None) -> bool:
        """Persist the detached controller identity used by ``cancel``."""
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE runs SET runner_pid = ?, runner_pgid = ?, updated_at = ? WHERE id = ?",
                (pid, pgid, utc_now(), run_id),
            ).rowcount
        return changed == 1

    def clear_runner_process(self, run_id: str, pid: int | None = None) -> bool:
        with self._connect() as connection:
            if pid is None:
                changed = connection.execute(
                    "UPDATE runs SET runner_pid = NULL, runner_pgid = NULL, updated_at = ? WHERE id = ?",
                    (utc_now(), run_id),
                ).rowcount
            else:
                changed = connection.execute(
                    "UPDATE runs SET runner_pid = NULL, runner_pgid = NULL, updated_at = ? "
                    "WHERE id = ? AND runner_pid = ?",
                    (utc_now(), run_id, pid),
                ).rowcount
        return changed == 1

    def dependency_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        """Return verified predecessor artifacts in deterministic order."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT run_id, dependencies FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown task: {task_id}")
            dependencies = json.loads(row["dependencies"] or "[]")
            if not dependencies:
                return []
            placeholders = ",".join("?" for _ in dependencies)
            rows = connection.execute(
                f"SELECT id, result_path FROM tasks WHERE run_id = ? AND id IN ({placeholders}) "
                "AND state = ?",
                [row["run_id"], *dependencies, TaskStatus.SUCCEEDED.value],
            ).fetchall()
            by_id = {item["id"]: item for item in rows}
            artifacts: list[dict[str, Any]] = []
            for dependency in dependencies:
                predecessor = by_id.get(dependency)
                if predecessor is None:
                    continue
                artifact_rows = connection.execute(
                    "SELECT path, sha256, size, kind FROM artifacts WHERE run_id = ? AND task_id = ? "
                    "ORDER BY created_at, id",
                    (row["run_id"], dependency),
                ).fetchall()
                for artifact in artifact_rows:
                    artifacts.append(
                        {
                            "task_id": dependency,
                            "path": artifact["path"],
                            "sha256": artifact["sha256"],
                            "size": artifact["size"],
                            "kind": artifact["kind"],
                        }
                    )
                if not artifact_rows and predecessor["result_path"]:
                    artifacts.append({"task_id": dependency, "path": predecessor["result_path"]})
            return artifacts

    def next_task(self, run_id: str) -> Task | None:
        with self._connect() as connection:
            # Promote dependency-free work and block work whose verified prerequisites can no
            # longer succeed. This is intentionally done in the same transaction as the claim
            # lookup so two local controllers cannot observe stale readiness.
            pending = connection.execute(
                "SELECT id, dependencies, state, input_question FROM tasks "
                "WHERE run_id = ? AND state IN (?, ?)",
                (run_id, TaskStatus.PENDING.value, TaskStatus.WAITING.value),
            ).fetchall()
            for row in pending:
                # WAITING is also used for dependency edges. A task with an input question is
                # paused by the session and must remain untouched until ``answer`` is called.
                if row["state"] == TaskStatus.WAITING.value and row["input_question"]:
                    continue
                dependencies = json.loads(row["dependencies"] or "[]")
                if not dependencies:
                    if row["state"] != TaskStatus.READY.value:
                        changed = connection.execute(
                            "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ? AND state IN (?, ?)",
                            (TaskStatus.READY.value, utc_now(), row["id"], TaskStatus.PENDING.value, TaskStatus.WAITING.value),
                        ).rowcount
                        if changed:
                            self._append_event(connection, run_id, row["id"], "task_ready", {})
                    continue
                placeholders = ",".join("?" for _ in dependencies)
                states = connection.execute(
                    f"SELECT id, state FROM tasks WHERE run_id = ? AND id IN ({placeholders})",
                    [run_id, *dependencies],
                ).fetchall()
                dependency_states = {item["id"]: item["state"] for item in states}
                if any(
                    dependency_states.get(dep)
                    in {
                        TaskStatus.FAILED.value,
                        TaskStatus.BLOCKED.value,
                        TaskStatus.CANCELLED.value,
                        TaskStatus.SUPERSEDED.value,
                    }
                    for dep in dependencies
                ):
                    changed = connection.execute(
                        "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? "
                        "WHERE id = ? AND state IN (?, ?)",
                        (
                            TaskStatus.BLOCKED.value,
                            "blocked because a dependency did not succeed",
                            utc_now(),
                            row["id"],
                            TaskStatus.PENDING.value,
                            TaskStatus.WAITING.value,
                        ),
                    ).rowcount
                    if changed:
                        self._append_event(
                            connection,
                            run_id,
                            row["id"],
                            "task_blocked",
                            {"dependencies": dependencies},
                        )
                elif all(dependency_states.get(dep) == TaskStatus.SUCCEEDED.value for dep in dependencies):
                    changed = connection.execute(
                        "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ? AND state IN (?, ?)",
                        (
                            TaskStatus.READY.value,
                            utc_now(),
                            row["id"],
                            TaskStatus.PENDING.value,
                            TaskStatus.WAITING.value,
                        ),
                    ).rowcount
                    if changed:
                        self._append_event(
                            connection,
                            run_id,
                            row["id"],
                            "task_ready",
                            {"dependencies": dependencies},
                        )
            row = connection.execute(
                "SELECT * FROM tasks WHERE run_id = ? AND state IN (?, ?) "
                "ORDER BY created_at, id LIMIT 1",
                (
                    run_id,
                    TaskStatus.READY.value,
                    TaskStatus.UNCERTAIN.value,
                ),
            ).fetchone()
        return self._task_from_row(row) if row else None

    def claim_task(self, task_id: str, runtime: str) -> Attempt | None:
        attempt_id = f"attempt-{uuid.uuid4().hex}"
        timestamp = utc_now()
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE tasks SET state = ?, attempts = attempts + 1, updated_at = ? "
                "WHERE id = ? AND state IN (?, ?, ?)",
                (
                    TaskStatus.RUNNING.value,
                    timestamp,
                    task_id,
                    TaskStatus.PENDING.value,
                    TaskStatus.READY.value,
                    TaskStatus.UNCERTAIN.value,
                ),
            ).rowcount
            if updated != 1:
                return None
            task = connection.execute("SELECT run_id, attempts FROM tasks WHERE id = ?", (task_id,)).fetchone()
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (RunStatus.RUNNING.value, timestamp, task["run_id"], RunStatus.PENDING.value),
            )
            connection.execute(
                "INSERT INTO attempts(id, task_id, runtime, status, started_at, heartbeat_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (attempt_id, task_id, runtime, "running", timestamp, timestamp),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_claimed",
                {"attempt_id": attempt_id, "runtime": runtime, "attempt": task["attempts"]},
            )
            row = connection.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        return self._attempt_from_row(row)

    def await_input(
        self,
        task_id: str,
        attempt_id: str,
        request_path: str,
        question: str,
        options: list[str] | tuple[str, ...] = (),
    ) -> bool:
        """Pause a running task until a user/parent Agent supplies an answer."""
        if not question.strip() or len(question.encode("utf-8")) > 8_000:
            raise ValueError("input question must be non-empty and at most 8 KiB")
        if len(options) > 10 or any(len(str(option).encode("utf-8")) > 200 for option in options):
            raise ValueError("input options exceed the limit")
        request = Path(request_path)
        if request.is_absolute() or ".." in request.parts:
            raise ValueError("input request path must be run-relative")
        timestamp = utc_now()
        normalized_options = [str(option) for option in options]
        with self._connect() as connection:
            task = connection.execute(
                "SELECT run_id FROM tasks WHERE id = ? AND state = ?",
                (task_id, TaskStatus.RUNNING.value),
            ).fetchone()
            if task is None:
                return False
            updated = connection.execute(
                "UPDATE tasks SET state = ?, input_question = ?, input_options = ?, "
                "input_answer_path = NULL, last_error = NULL, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (
                    TaskStatus.WAITING.value,
                    question,
                    json.dumps(normalized_options, ensure_ascii=False),
                    timestamp,
                    task_id,
                    TaskStatus.RUNNING.value,
                ),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = NULL "
                "WHERE id = ? AND status = ?",
                ("awaiting_input", timestamp, timestamp, attempt_id, "running"),
            )
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                (RunStatus.AWAITING_INPUT.value, timestamp, task["run_id"], RunStatus.CANCELLED.value),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "input_required",
                {
                    "attempt_id": attempt_id,
                    "request_path": request_path,
                    "question_bytes": len(question.encode("utf-8")),
                    "options_count": len(normalized_options),
                },
            )
        return True

    def pending_input(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, input_question, input_options, input_answer_path FROM tasks "
                "WHERE run_id = ? AND state = ? ORDER BY created_at, id LIMIT 1",
                (run_id, TaskStatus.WAITING.value),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": run_id,
            "task_id": row["id"],
            "question": row["input_question"],
            "options": json.loads(row["input_options"] or "[]"),
            "request_path": self._input_request_path(run_id, row["id"]),
            "answer_path": row["input_answer_path"],
        }

    def answer_input(self, run_id: str, answer_path: str) -> str | None:
        """Attach an answer artifact and make the waiting task ready again."""
        path = Path(answer_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("input answer path must be run-relative")
        timestamp = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM tasks WHERE run_id = ? AND state = ? ORDER BY created_at, id LIMIT 1",
                (run_id, TaskStatus.WAITING.value),
            ).fetchone()
            if row is None:
                return None
            task_id = row["id"]
            updated = connection.execute(
                "UPDATE tasks SET state = ?, input_answer_path = ?, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (TaskStatus.READY.value, answer_path, timestamp, task_id, TaskStatus.WAITING.value),
            ).rowcount
            if updated != 1:
                return None
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (RunStatus.PENDING.value, timestamp, run_id, RunStatus.AWAITING_INPUT.value),
            )
            self._append_event(
                connection,
                run_id,
                task_id,
                "input_answered",
                {"answer_path": answer_path},
            )
        return task_id

    def _input_request_path(self, run_id: str, task_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path FROM artifacts WHERE run_id = ? AND task_id = ? AND kind = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (run_id, task_id, "input"),
            ).fetchone()
        return row["path"] if row else None

    def finish_task(
        self,
        task_id: str,
        attempt_id: str,
        success: bool,
        result_path: str | None = None,
        error: str | None = None,
    ) -> bool:
        timestamp = utc_now()
        new_state = TaskStatus.SUCCEEDED.value if success else TaskStatus.FAILED.value
        attempt_state = "succeeded" if success else "failed"
        with self._connect() as connection:
            task = connection.execute("SELECT run_id, state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"unknown task: {task_id}")
            updated = connection.execute(
                "UPDATE tasks SET state = ?, result_path = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (new_state, result_path, error, timestamp, task_id, TaskStatus.RUNNING.value),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? WHERE id = ?",
                (attempt_state, timestamp, timestamp, error, attempt_id),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_succeeded" if success else "task_failed",
                {"attempt_id": attempt_id, "result_path": result_path, "error": error},
            )
        return True

    def retry_task(self, task_id: str, attempt_id: str, error: str) -> bool:
        timestamp = utc_now()
        with self._connect() as connection:
            task = connection.execute("SELECT run_id, state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"unknown task: {task_id}")
            updated = connection.execute(
                "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (TaskStatus.READY.value, error, timestamp, task_id, TaskStatus.RUNNING.value),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? WHERE id = ?",
                ("failed", timestamp, timestamp, error, attempt_id),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_retry_scheduled",
                {"attempt_id": attempt_id, "error": error},
            )
        return True

    def set_attempt_process(self, attempt_id: str, pid: int | None, pgid: int | None) -> bool:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE attempts SET pid = ?, pgid = ?, heartbeat_at = ? WHERE id = ?",
                (pid, pgid, utc_now(), attempt_id),
            ).rowcount
        return changed == 1

    def recover_running(self, run_id: str) -> int:
        timestamp = utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM tasks WHERE run_id = ? AND state = ?",
                (run_id, TaskStatus.RUNNING.value),
            ).fetchall()
            for row in rows:
                task_id = row["id"]
                connection.execute(
                    "UPDATE tasks SET state = ?, updated_at = ?, last_error = ? WHERE id = ?",
                    (
                        TaskStatus.UNCERTAIN.value,
                        timestamp,
                        "controller restarted while task was running",
                        task_id,
                    ),
                )
                connection.execute(
                    "UPDATE attempts SET status = ?, heartbeat_at = ?, error = ? "
                    "WHERE task_id = ? AND status = ?",
                    (
                        "uncertain",
                        timestamp,
                        "controller restarted before attempt completed",
                        task_id,
                        "running",
                    ),
                )
                self._append_event(
                    connection,
                    run_id,
                    task_id,
                    "task_recovered",
                    {"reason": "controller_restart"},
                )
        return len(rows)

    def settle_run(self, run_id: str) -> Run | None:
        timestamp = utc_now()
        with self._connect() as connection:
            current = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if current is None:
                return None
            rows = connection.execute("SELECT state FROM tasks WHERE run_id = ?", (run_id,)).fetchall()
            if not rows:
                return self.get_run(run_id)
            states = {row["state"] for row in rows}
            if TaskStatus.FAILED.value in states or TaskStatus.BLOCKED.value in states:
                status = RunStatus.FAILED.value
            elif states and states.issubset({TaskStatus.SUCCEEDED.value, TaskStatus.SUPERSEDED.value}) and TaskStatus.SUCCEEDED.value in states:
                status = RunStatus.SUCCEEDED.value
            elif TaskStatus.WAITING.value in states:
                status = RunStatus.AWAITING_INPUT.value
            elif TaskStatus.CANCELLED.value in states:
                status = RunStatus.CANCELLED.value
            else:
                status = RunStatus.RUNNING.value
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                (status, timestamp, run_id, RunStatus.CANCELLED.value),
            )
            if (
                status in {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value}
                and current["status"] != status
            ):
                self._append_event(connection, run_id, None, f"run_{status}", {})
        return self.get_run(run_id)

    def cancel_run(self, run_id: str) -> bool:
        timestamp = utc_now()
        with self._connect() as connection:
            run = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                return False
            changed = connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status NOT IN (?, ?, ?)",
                (
                    RunStatus.CANCELLED.value,
                    timestamp,
                    run_id,
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                ),
            ).rowcount
            task_rows = connection.execute(
                "SELECT id FROM tasks WHERE run_id = ? AND state NOT IN (?, ?, ?, ?)",
                (
                    run_id,
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                    TaskStatus.SUPERSEDED.value,
                ),
            ).fetchall()
            changed_tasks = connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE run_id = ? AND state NOT IN (?, ?, ?, ?)",
                (
                    TaskStatus.CANCELLED.value,
                    timestamp,
                    run_id,
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                    TaskStatus.SUPERSEDED.value,
                ),
            ).rowcount
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ? WHERE task_id IN "
                "(SELECT id FROM tasks WHERE run_id = ?) AND status = ?",
                ("cancelled", timestamp, run_id, "running"),
            )
            if changed:
                self._append_event(connection, run_id, None, "run_cancelled", {})
                if changed_tasks:
                    for row in task_rows:
                        self._append_event(
                            connection,
                            run_id,
                            row["id"],
                            "task_cancelled",
                            {"reason": "run_cancelled"},
                        )
        return bool(changed)

    def add_artifact(
        self,
        run_id: str,
        task_id: str,
        path: str,
        sha256: str,
        size: int,
        kind: str = "result",
    ) -> str:
        artifact_id = f"artifact-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO artifacts(id, run_id, task_id, path, sha256, size, kind, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, run_id, task_id, path, sha256, size, kind, utc_now()),
            )
            self._append_event(
                connection,
                run_id,
                task_id,
                "artifact_recorded",
                {"artifact_id": artifact_id, "path": path, "sha256": sha256, "size": size},
            )
        return artifact_id

    def discard_attempt_outputs(self, run_id: str, task_id: str, attempt_id: str) -> list[str]:
        """Remove late result/runtime metadata while retaining the prompt and audit event."""
        prefix = f"tasks/{task_id}/{attempt_id}/"
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT path FROM artifacts WHERE run_id = ? AND task_id = ? AND path LIKE ? "
                "AND kind IN (?, ?)",
                (run_id, task_id, prefix + "%", "result", "runtime"),
            ).fetchall()
            connection.execute(
                "DELETE FROM artifacts WHERE run_id = ? AND task_id = ? AND path LIKE ? "
                "AND kind IN (?, ?)",
                (run_id, task_id, prefix + "%", "result", "runtime"),
            )
        return [row["path"] for row in rows]

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, task_id, path, sha256, size, kind, created_at FROM artifacts "
                "WHERE run_id = ? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, task_id, type, payload, created_at FROM events "
                "WHERE run_id = ? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "type": row["type"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        event_id: str | None = None,
    ) -> bool:
        with self._connect() as connection:
            return self._append_event(connection, run_id, task_id, event_type, payload, event_id)

    def fail_budget(self, run_id: str, limit: str, actual: float, maximum: float, reason: str) -> bool:
        """Record a fail-closed budget violation and transition unfinished work to failed."""
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None or row["status"] in {RunStatus.SUCCEEDED.value, RunStatus.CANCELLED.value}:
                return False
            timestamp = utc_now()
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                (RunStatus.FAILED.value, timestamp, run_id, RunStatus.CANCELLED.value),
            )
            connection.execute(
                "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? WHERE run_id = ? AND state IN (?, ?, ?, ?)",
                (TaskStatus.BLOCKED.value, reason, timestamp, run_id, TaskStatus.PENDING.value, TaskStatus.READY.value, TaskStatus.WAITING.value, TaskStatus.RUNNING.value),
            )
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? WHERE task_id IN (SELECT id FROM tasks WHERE run_id = ?) AND status = ?",
                ("failed", timestamp, timestamp, reason, run_id, "running"),
            )
            return self._append_event(
                connection, run_id, None, "budget_exceeded",
                {"limit": limit, "actual": actual, "maximum": maximum, "reason": reason},
                event_id=f"event-budget-{limit}-{run_id}",
            )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        run_id: str,
        task_id: str | None,
        event_type: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> bool:
        event_id = event_id or f"event-{uuid.uuid4().hex}"
        inserted = connection.execute(
            "INSERT OR IGNORE INTO events(id, run_id, task_id, type, payload, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (event_id, run_id, task_id, event_type, json.dumps(payload, sort_keys=True), utc_now()),
        ).rowcount
        return inserted == 1

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        result_path = Path(row["result_path"]) if row["result_path"] else None
        return Task(
            id=row["id"],
            run_id=row["run_id"],
            title=row["title"],
            prompt=row["prompt"],
            state=TaskStatus(row["state"]),
            attempts=row["attempts"],
            result_path=result_path,
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            dependencies=tuple(json.loads(row["dependencies"] or "[]")),
            acceptance=row["acceptance"],
            input_question=row["input_question"],
            input_options=tuple(json.loads(row["input_options"] or "[]")),
            input_answer_path=Path(row["input_answer_path"]) if row["input_answer_path"] else None,
            plan_task_id=row["plan_task_id"],
        )

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> Attempt:
        return Attempt(
            id=row["id"],
            task_id=row["task_id"],
            runtime=row["runtime"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
            pid=row["pid"],
            pgid=row["pgid"],
        )
