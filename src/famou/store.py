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

from .models import Attempt, Run, RunStatus, Task, TaskStatus

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
    runner_pgid INTEGER
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
            # Keep upgrades compatible with the P1 database created before plans and detached
            # process metadata existed. SQLite has no IF NOT EXISTS form for ADD COLUMN.
            self._ensure_column(connection, "runs", "runner_pid", "INTEGER")
            self._ensure_column(connection, "runs", "runner_pgid", "INTEGER")
            self._ensure_column(connection, "tasks", "dependencies", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "tasks", "acceptance", "TEXT")
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

    def create_run(
        self,
        goal: str,
        workspace: str | Path | None = None,
        tasks: list[dict[str, Any]] | None = None,
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
                "INSERT INTO runs(id, goal, status, workspace, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (run_id, goal, RunStatus.PENDING.value, str(workspace_path), timestamp, timestamp),
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
                {"goal": goal, "task_count": len(normalized)},
            )
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
                "SELECT id, dependencies, state FROM tasks WHERE run_id = ? AND state IN (?, ?)",
                (run_id, TaskStatus.PENDING.value, TaskStatus.WAITING.value),
            ).fetchall()
            for row in pending:
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
            elif states == {TaskStatus.SUCCEEDED.value}:
                status = RunStatus.SUCCEEDED.value
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
                "SELECT id FROM tasks WHERE run_id = ? AND state NOT IN (?, ?, ?)",
                (
                    run_id,
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                ),
            ).fetchall()
            changed_tasks = connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE run_id = ? AND state NOT IN (?, ?, ?)",
                (
                    TaskStatus.CANCELLED.value,
                    timestamp,
                    run_id,
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
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
