"""Controller-owned local SQLite evidence store.

This is deliberately an offline storage primitive.  It does not authenticate
callers and must only be reached through a host boundary that can prove one.
"""

import contextlib
import hashlib
import json
import sqlite3
from pathlib import Path

from runtime_contract import validate_record, validate_attempt_transition


SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 2_000


class StorageError(RuntimeError):
    pass


class UnsupportedStorageRoot(StorageError):
    pass


class RuntimeStore:
    def __init__(self, state_root, busy_timeout_ms=BUSY_TIMEOUT_MS):
        root = Path(state_root)
        if not root.is_absolute() or root.name != "state" or root.is_symlink() or root.resolve() != root:
            raise UnsupportedStorageRoot("runtime storage must be an absolute, non-symlink state directory")
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.root.is_dir() or self.root.is_symlink() or not self._is_supported_local_root(self.root):
            raise UnsupportedStorageRoot("runtime storage is not a safe directory")
        self.db_path = self.root / "runtime.sqlite3"
        self.busy_timeout_ms = int(busy_timeout_ms)
        if self.busy_timeout_ms < 1 or self.busy_timeout_ms > 30_000:
            raise ValueError("busy timeout must be bounded")
        self._fail_next_write = False
        self._migrate()

    @staticmethod
    def _is_supported_local_root(root):
        """Reject known remote filesystem types; unknown types are unsupported.

        This implementation is intentionally Linux-local because that is the
        only platform on which this runtime currently makes a storage claim.
        """
        try:
            mounts = []
            for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
                fields = line.split()
                if len(fields) >= 3:
                    mounts.append((Path(fields[1]), fields[2]))
            mount, filesystem = max((entry for entry in mounts if root.is_relative_to(entry[0])), key=lambda entry: len(str(entry[0])))
        except (OSError, ValueError):
            return False
        return filesystem not in {"nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs"}

    def _connect(self):
        connection = sqlite3.connect(str(self.db_path), timeout=self.busy_timeout_ms / 1000, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = %d" % self.busy_timeout_ms)
        return connection

    def _migrate(self):
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            if SCHEMA_VERSION not in applied:
                connection.executescript("""
                CREATE TABLE runs (run_id TEXT PRIMARY KEY, record_json TEXT NOT NULL, state TEXT NOT NULL);
                CREATE TABLE preflights (preflight_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), record_json TEXT NOT NULL);
                CREATE TABLE tasks (task_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), record_json TEXT NOT NULL);
                CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), task_id TEXT NOT NULL REFERENCES tasks(task_id), record_json TEXT NOT NULL, state TEXT NOT NULL, last_envelope_id TEXT);
                CREATE TABLE envelopes (envelope_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), task_id TEXT, attempt_id TEXT REFERENCES attempts(attempt_id), dedup_key TEXT NOT NULL, body BLOB NOT NULL, body_sha256 TEXT NOT NULL, source_metadata_json TEXT NOT NULL, record_json TEXT NOT NULL, correction_of TEXT REFERENCES envelopes(envelope_id), UNIQUE(dedup_key, body_sha256));
                CREATE TABLE events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(run_id), task_id TEXT, attempt_id TEXT REFERENCES attempts(attempt_id), dedup_key TEXT, kind TEXT NOT NULL, record_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE decisions (decision_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), attempt_id TEXT REFERENCES attempts(attempt_id), record_json TEXT NOT NULL);
                CREATE TABLE workspace_reservations (workspace_fingerprint TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id), attempt_id TEXT REFERENCES attempts(attempt_id), state TEXT NOT NULL, record_json TEXT NOT NULL);
                CREATE INDEX envelopes_dedup_identity ON envelopes(dedup_key);
                CREATE INDEX events_attempt ON events(attempt_id);
                """)
                connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))

    @contextlib.contextmanager
    def _mutation(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            if self._fail_next_write:
                self._fail_next_write = False
                raise OSError("injected disk write failure")
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise StorageError(str(exc)) from exc
        except OSError as exc:
            connection.execute("ROLLBACK")
            raise StorageError(str(exc)) from exc
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def fail_next_write_for_test(self):
        self._fail_next_write = True

    def create_run(self, record):
        errors = validate_record("run", record)
        if errors:
            raise StorageError("invalid run: " + "; ".join(errors))
        with self._mutation() as connection:
            connection.execute("INSERT INTO runs(run_id, record_json, state) VALUES (?, ?, ?)",
                               (record["run_id"], self._json(record), record["state"]))

    def create_attempt(self, record):
        errors = validate_record("attempt", record)
        if errors:
            raise StorageError("invalid attempt: " + "; ".join(errors))
        with self._mutation() as connection:
            connection.execute("INSERT OR IGNORE INTO tasks(task_id, run_id, record_json) VALUES (?, ?, ?)",
                               (record["task_id"], record["run_id"], self._json({"task_id": record["task_id"]})))
            connection.execute("INSERT INTO attempts(attempt_id, run_id, task_id, record_json, state, last_envelope_id) VALUES (?, ?, ?, ?, ?, ?)",
                               (record["attempt_id"], record["run_id"], record["task_id"], self._json(record), record["state"], record["last_envelope_id"]))

    def capture_result(self, envelope, body, dedup_key, new_state, fail_before_commit=False):
        if not isinstance(body, bytes) or not isinstance(dedup_key, str) or not dedup_key:
            raise StorageError("body must be bytes and dedup_key must be non-empty")
        if hashlib.sha256(body).hexdigest() != envelope.get("body_sha256"):
            raise StorageError("envelope hash does not match raw bytes")
        errors = validate_record("envelope", envelope)
        if errors:
            raise StorageError("invalid envelope: " + "; ".join(errors))
        with self._mutation() as connection:
            existing = connection.execute("SELECT * FROM envelopes WHERE dedup_key = ?", (dedup_key,)).fetchone()
            if existing:
                if existing["body_sha256"] == envelope["body_sha256"]:
                    return {"status": "captured", "envelope_id": existing["envelope_id"], "replayed": True}
                # Preserve the contradictory raw result and block the governed run.
                connection.execute("INSERT INTO envelopes(envelope_id, run_id, task_id, attempt_id, dedup_key, body, body_sha256, source_metadata_json, record_json, correction_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (envelope["envelope_id"], envelope["run_id"], envelope["task_id"], envelope["attempt_id"], dedup_key, body, envelope["body_sha256"], self._json(self._source_metadata(envelope)), self._json(envelope), existing["envelope_id"]))
                connection.execute("UPDATE runs SET state = 'blocked' WHERE run_id = ?", (envelope["run_id"],))
                self._append_event(connection, envelope, dedup_key, "conflicting_provider_result")
                return {"status": "conflict", "envelope_id": envelope["envelope_id"], "original_envelope_id": existing["envelope_id"]}
            attempt = connection.execute("SELECT * FROM attempts WHERE attempt_id = ?", (envelope["attempt_id"],)).fetchone()
            if attempt is None or attempt["run_id"] != envelope["run_id"] or attempt["task_id"] != envelope["task_id"]:
                raise StorageError("envelope does not belong to an existing attempt")
            transition_errors = validate_attempt_transition(attempt["state"], new_state)
            if transition_errors:
                raise StorageError("; ".join(transition_errors))
            if fail_before_commit:
                raise StorageError("injected failure before commit")
            connection.execute("INSERT INTO envelopes(envelope_id, run_id, task_id, attempt_id, dedup_key, body, body_sha256, source_metadata_json, record_json, correction_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                               (envelope["envelope_id"], envelope["run_id"], envelope["task_id"], envelope["attempt_id"], dedup_key, body, envelope["body_sha256"], self._json(self._source_metadata(envelope)), self._json(envelope)))
            connection.execute("UPDATE attempts SET state = ?, last_envelope_id = ? WHERE attempt_id = ?", (new_state, envelope["envelope_id"], envelope["attempt_id"]))
            self._append_event(connection, envelope, dedup_key, "result_captured")
            return {"status": "captured", "envelope_id": envelope["envelope_id"], "replayed": False}

    @staticmethod
    def _source_metadata(envelope):
        return {field: envelope[field] for field in ("capture_source", "captured_by", "provider_thread_id", "provider_turn_id", "provider_event_id")}

    def _append_event(self, connection, envelope, dedup_key, kind):
        connection.execute("INSERT INTO events(run_id, task_id, attempt_id, dedup_key, kind, record_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (envelope["run_id"], envelope["task_id"], envelope["attempt_id"], dedup_key, kind, self._json({"kind": kind, "envelope_id": envelope["envelope_id"]}), envelope["created_at"]))

    def count(self, table):
        if table not in {"runs", "preflights", "tasks", "attempts", "envelopes", "events", "decisions", "workspace_reservations"}:
            raise ValueError("unknown table")
        with self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def attempt_state(self, attempt_id):
        with self._connect() as connection:
            row = connection.execute("SELECT state FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
            return None if row is None else row[0]

    def run_state(self, run_id):
        with self._connect() as connection:
            row = connection.execute("SELECT state FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return None if row is None else row[0]

    def export(self, destination, fail_after=None):
        """Generate disposable exports; this method never reads existing exports."""
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            runs = [json.loads(row[0]) for row in connection.execute("SELECT record_json FROM runs ORDER BY run_id")]
            attempts = [json.loads(row[0]) for row in connection.execute("SELECT record_json FROM attempts ORDER BY attempt_id")]
            payload = {"schema_version": SCHEMA_VERSION, "runs": runs, "attempts": attempts}
        json_path = destination / "runtime.json"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if fail_after == "json":
            raise OSError("injected partial export")
        lines = ["# Runtime export", "", "## Runs", ""] + ["- %s: %s" % (run["run_id"], run["state"]) for run in runs]
        (destination / "runtime.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
