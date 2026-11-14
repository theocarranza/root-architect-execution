"""Controller-owned local SQLite evidence store.

This is deliberately an offline storage primitive.  It does not authenticate
callers and must only be reached through a host boundary that can prove one.
"""

import contextlib
import hashlib
import json
import sqlite3
from pathlib import Path

from runtime_contract import (
    validate_attempt,
    validate_attempt_transition,
    validate_outcome,
    validate_record,
)
import render_agents


SCHEMA_VERSION = 5
BUSY_TIMEOUT_MS = 2_000
TEMPLATE_IDENTITY_FIELDS = (
    "family",
    "selected_template",
    "template_catalog_sha256",
    "requested_model_tier",
    "requested_effort",
    "resolved_model",
    "resolved_effort",
    "effective_model",
    "effective_effort",
)


class StorageError(RuntimeError):
    pass


class UnsupportedStorageRoot(StorageError):
    pass


class RuntimeStore:
    def __init__(self, state_root, busy_timeout_ms=BUSY_TIMEOUT_MS):
        root = Path(state_root)
        if (
            not root.is_absolute()
            or root.name != "state"
            or root.is_symlink()
            or root.resolve() != root
        ):
            raise UnsupportedStorageRoot(
                "runtime storage must be an absolute, non-symlink state directory"
            )
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (
            not self.root.is_dir()
            or self.root.is_symlink()
            or not self._is_supported_local_root(self.root)
        ):
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
            mount, filesystem = max(
                (entry for entry in mounts if root.is_relative_to(entry[0])),
                key=lambda entry: len(str(entry[0])),
            )
        except (OSError, ValueError):
            return False
        return filesystem not in {"nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs"}

    def _connect(self):
        connection = sqlite3.connect(
            str(self.db_path), timeout=self.busy_timeout_ms / 1000, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = %d" % self.busy_timeout_ms)
        return connection

    def _migrate(self):
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
            )
            applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations")
            }
            if 1 not in applied:
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
                connection.execute("INSERT INTO schema_migrations(version) VALUES (1)")
            if 2 not in applied:
                connection.execute("""
                CREATE TABLE launches (
                    attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id),
                    workspace_fingerprint TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    intended_parent TEXT NOT NULL,
                    provider_thread_id TEXT,
                    state TEXT NOT NULL
                )
                """)
                connection.execute("INSERT INTO schema_migrations(version) VALUES (2)")
            if 3 not in applied:
                connection.execute("ALTER TABLE launches ADD COLUMN dispatch_envelope_id TEXT")
                connection.execute(
                    "ALTER TABLE launches ADD COLUMN purpose TEXT NOT NULL DEFAULT 'implementation'"
                )
                connection.execute(
                    "ALTER TABLE launches ADD COLUMN parent_attempt_id TEXT REFERENCES attempts(attempt_id)"
                )
                connection.execute(
                    "ALTER TABLE launches ADD COLUMN source_envelope_id TEXT REFERENCES envelopes(envelope_id)"
                )
                connection.executescript("""
                CREATE TABLE attempt_lineage (
                    attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id),
                    parent_attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                    purpose TEXT NOT NULL,
                    source_envelope_id TEXT NOT NULL REFERENCES envelopes(envelope_id)
                );
                CREATE TABLE format_corrections (
                    source_envelope_id TEXT PRIMARY KEY REFERENCES envelopes(envelope_id),
                    attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(attempt_id)
                );
                CREATE TABLE validations (
                    attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id),
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    envelope_id TEXT NOT NULL REFERENCES envelopes(envelope_id),
                    valid INTEGER NOT NULL CHECK(valid IN (0,1)),
                    validator_ref TEXT NOT NULL,
                    principal_id TEXT NOT NULL
                );
                """)
                connection.execute("INSERT INTO schema_migrations(version) VALUES (3)")
            if 4 not in applied:
                connection.execute(
                    "CREATE UNIQUE INDEX one_decision_per_attempt "
                    "ON decisions(run_id, attempt_id) WHERE attempt_id IS NOT NULL"
                )
                connection.execute("INSERT INTO schema_migrations(version) VALUES (4)")
            if 5 not in applied:
                connection.execute("""
                CREATE TABLE run_template_catalogs (
                    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                    host_id TEXT NOT NULL,
                    catalog_sha256 TEXT NOT NULL,
                    catalog_json TEXT NOT NULL
                )
                """)
                connection.execute("INSERT INTO schema_migrations(version) VALUES (5)")

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

    def create_run(self, record, template_catalog):
        """Persist a run and its explicit controller-owned catalog snapshot.

        This local store does not authenticate the caller. The host boundary
        must supply the catalog from trusted controller state.
        """
        errors = validate_record("run", record)
        if errors:
            raise StorageError("invalid run: " + "; ".join(errors))
        catalog_errors = render_agents.validate_catalog(template_catalog)
        if catalog_errors:
            raise StorageError(
                "invalid controller-owned template catalog: " + "; ".join(catalog_errors)
            )
        if record["host_id"] != template_catalog["host"]:
            raise StorageError("template catalog host does not match the run host")
        with self._mutation() as connection:
            connection.execute(
                "INSERT INTO runs(run_id, record_json, state) VALUES (?, ?, ?)",
                (record["run_id"], self._json(record), record["state"]),
            )
            connection.execute(
                "INSERT INTO run_template_catalogs(run_id, host_id, catalog_sha256, catalog_json) VALUES (?, ?, ?, ?)",
                (
                    record["run_id"],
                    template_catalog["host"],
                    template_catalog["catalog_sha256"],
                    self._json(template_catalog),
                ),
            )

    def create_attempt(self, record):
        raise StorageError(
            "direct attempt creation is unsupported; use the reserved launch lifecycle"
        )

    @staticmethod
    def _reservation_is_live(state):
        # Reservations exist only while this row is present; status alone never
        # proves a child writer stopped.
        return True

    def reserve_attempt(
        self,
        record,
        workspace_fingerprint,
        idempotency_key,
        intended_parent,
        dispatch_envelope,
        dispatch_body,
        purpose="implementation",
        parent_attempt_id=None,
        source_envelope_id=None,
    ):
        """Atomically persist attempt and workspace/launch reservation before host start."""
        errors = validate_record("attempt", record)
        if errors:
            raise StorageError("invalid attempt: " + "; ".join(errors))
        if not all(
            isinstance(value, str) and value
            for value in (workspace_fingerprint, idempotency_key, intended_parent)
        ):
            raise StorageError("workspace, launch key, and intended parent are required")
        if not isinstance(dispatch_body, bytes) or not isinstance(dispatch_envelope, dict):
            raise StorageError("a captured dispatch envelope and its exact raw bytes are required")
        if hashlib.sha256(dispatch_body).hexdigest() != dispatch_envelope.get("body_sha256"):
            raise StorageError("dispatch envelope hash does not match its raw bytes")
        if purpose not in {
            "implementation",
            "specification",
            "quality",
            "repair",
            "escalation",
            "format_correction",
        }:
            raise StorageError("attempt purpose is unsupported")
        if purpose == "implementation" and (
            parent_attempt_id is not None or source_envelope_id is not None
        ):
            raise StorageError("initial implementation attempt cannot claim lineage")
        if purpose != "implementation" and (not parent_attempt_id or not source_envelope_id):
            raise StorageError("follow-up attempts require a parent attempt and source evidence")
        family_prefix = {
            "implementation": "impl-",
            "specification": "spec-",
            "quality": "quality-",
        }.get(purpose)
        if family_prefix and not record["selected_template"].startswith(family_prefix):
            raise StorageError("selected template does not match the attempt purpose")
        if record["state"] != "reserved":
            raise StorageError("new launch attempts must begin reserved")
        with self._mutation() as connection:
            run = connection.execute(
                "SELECT record_json FROM runs WHERE run_id = ?", (record["run_id"],)
            ).fetchone()
            if (
                run is None
                or json.loads(run[0]).get("workspace_fingerprint") != workspace_fingerprint
            ):
                raise StorageError("workspace fingerprint does not match the run")
            run_record = json.loads(run[0])
            catalog_row = connection.execute(
                "SELECT host_id, catalog_sha256, catalog_json FROM run_template_catalogs WHERE run_id=?",
                (record["run_id"],),
            ).fetchone()
            if catalog_row is None:
                raise StorageError("run has no persisted controller-owned template catalog")
            catalog = json.loads(catalog_row["catalog_json"])
            if catalog_row["host_id"] != run_record["host_id"] or catalog_row[
                "catalog_sha256"
            ] != catalog.get("catalog_sha256"):
                raise StorageError("persisted template catalog identity is inconsistent")
            errors = validate_attempt(record, catalog)
            if errors:
                raise StorageError("invalid attempt template selection: " + "; ".join(errors))
            dispatch_errors = validate_record("envelope", dispatch_envelope)
            if dispatch_errors:
                raise StorageError("invalid dispatch envelope: " + "; ".join(dispatch_errors))
            expected_dispatch = {
                "run_id": record["run_id"],
                "task_id": record["task_id"],
                "attempt_id": record["attempt_id"],
                "kind": "task",
                "from": "orchestrator",
                "to": "worker:" + record["selected_template"],
                "captured_by": run_record["principal_id"],
                "selected_template": record["selected_template"],
            }
            expected_dispatch.update({field: record[field] for field in TEMPLATE_IDENTITY_FIELDS})
            if any(dispatch_envelope.get(key) != value for key, value in expected_dispatch.items()):
                raise StorageError("dispatch envelope does not match the controller-owned attempt")
            existing = connection.execute(
                "SELECT attempt_id, state FROM workspace_reservations WHERE workspace_fingerprint = ?",
                (workspace_fingerprint,),
            ).fetchone()
            if (
                existing
                and existing["attempt_id"] != record["attempt_id"]
                and self._reservation_is_live(existing["state"])
            ):
                raise StorageError("workspace already has a dependent attempt reserved or active")
            parent = None
            if parent_attempt_id is not None:
                parent = connection.execute(
                    "SELECT run_id, state, last_envelope_id, record_json FROM attempts WHERE attempt_id=?",
                    (parent_attempt_id,),
                ).fetchone()
                if (
                    parent is None
                    or parent["run_id"] != record["run_id"]
                    or parent["last_envelope_id"] != source_envelope_id
                    or parent["state"] not in {"invalid", "validated"}
                ):
                    raise StorageError(
                        "follow-up attempt must link to a validated or invalid parent return"
                    )
                if (
                    connection.execute(
                        "SELECT 1 FROM envelopes WHERE envelope_id=? AND attempt_id=?",
                        (source_envelope_id, parent_attempt_id),
                    ).fetchone()
                    is None
                ):
                    raise StorageError(
                        "follow-up source evidence does not belong to its parent attempt"
                    )
                prerequisite = connection.execute(
                    "SELECT d.record_json FROM decisions d WHERE d.attempt_id=? ORDER BY d.decision_id",
                    (parent_attempt_id,),
                ).fetchall()
                decisions = [json.loads(row[0])["decision"] for row in prerequisite]
                required_decisions = (
                    {"format_correction"}
                    if purpose == "format_correction"
                    else {"reject", "repair", "escalate"}
                    if purpose in {"repair", "escalation"}
                    else {"accept"}
                )
                if not required_decisions.intersection(decisions):
                    raise StorageError(
                        "follow-up attempt requires a recorded orchestrator decision"
                    )
                if (
                    purpose == "format_correction"
                    and connection.execute(
                        "SELECT 1 FROM format_corrections WHERE source_envelope_id=?",
                        (source_envelope_id,),
                    ).fetchone()
                ):
                    raise StorageError("a worker return may receive only one format correction")
                if purpose in {"repair", "escalation", "format_correction"}:
                    parent_template = json.loads(parent["record_json"])["selected_template"]
                    if record["selected_template"].split("-")[0] != parent_template.split("-")[0]:
                        raise StorageError(
                            "repair and escalation attempts must preserve the worker family"
                        )
            connection.execute(
                "INSERT INTO tasks(task_id, run_id, record_json) VALUES (?, ?, ?)",
                (record["task_id"], record["run_id"], self._json({"task_id": record["task_id"]})),
            )
            connection.execute(
                "INSERT INTO attempts(attempt_id, run_id, task_id, record_json, state, last_envelope_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record["attempt_id"],
                    record["run_id"],
                    record["task_id"],
                    self._json(record),
                    record["state"],
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO envelopes(envelope_id, run_id, task_id, attempt_id, dedup_key, body, body_sha256, source_metadata_json, record_json, correction_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    dispatch_envelope["envelope_id"],
                    record["run_id"],
                    record["task_id"],
                    record["attempt_id"],
                    "dispatch:" + idempotency_key,
                    dispatch_body,
                    dispatch_envelope["body_sha256"],
                    self._json(self._source_metadata(dispatch_envelope)),
                    self._json(dispatch_envelope),
                ),
            )
            connection.execute(
                "INSERT INTO workspace_reservations(workspace_fingerprint, run_id, attempt_id, state, record_json) VALUES (?, ?, ?, ?, ?)",
                (
                    workspace_fingerprint,
                    record["run_id"],
                    record["attempt_id"],
                    record["state"],
                    self._json({"attempt_id": record["attempt_id"]}),
                ),
            )
            connection.execute(
                "INSERT INTO launches(attempt_id, workspace_fingerprint, idempotency_key, intended_parent, provider_thread_id, state, dispatch_envelope_id, purpose, parent_attempt_id, source_envelope_id) VALUES (?, ?, ?, ?, NULL, 'reserved', ?, ?, ?, ?)",
                (
                    record["attempt_id"],
                    workspace_fingerprint,
                    idempotency_key,
                    intended_parent,
                    dispatch_envelope["envelope_id"],
                    purpose,
                    parent_attempt_id,
                    source_envelope_id,
                ),
            )
            if parent_attempt_id is not None:
                connection.execute(
                    "INSERT INTO attempt_lineage(attempt_id, parent_attempt_id, purpose, source_envelope_id) VALUES (?, ?, ?, ?)",
                    (record["attempt_id"], parent_attempt_id, purpose, source_envelope_id),
                )
                if purpose == "format_correction":
                    connection.execute(
                        "INSERT INTO format_corrections(source_envelope_id, attempt_id) VALUES (?, ?)",
                        (source_envelope_id, record["attempt_id"]),
                    )

    def reserve_followup_attempt(
        self,
        record,
        workspace_fingerprint,
        idempotency_key,
        intended_parent,
        dispatch_envelope,
        dispatch_body,
        purpose,
        parent_attempt_id,
    ):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_envelope_id FROM attempts WHERE attempt_id=?", (parent_attempt_id,)
            ).fetchone()
        if row is None or row["last_envelope_id"] is None:
            raise StorageError("follow-up parent has no captured return")
        return self.reserve_attempt(
            record,
            workspace_fingerprint,
            idempotency_key,
            intended_parent,
            dispatch_envelope,
            dispatch_body,
            purpose,
            parent_attempt_id,
            row["last_envelope_id"],
        )

    def record_machine_validation(self, attempt_id, valid, validator_ref):
        if type(valid) is not bool or not isinstance(validator_ref, str) or not validator_ref:
            raise StorageError("machine validation requires a boolean result and reference")
        with self._mutation() as connection:
            attempt = connection.execute(
                "SELECT run_id, state, last_envelope_id FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["state"] != "captured" or not attempt["last_envelope_id"]:
                raise StorageError("machine validation requires one captured return")
            run = connection.execute(
                "SELECT record_json FROM runs WHERE run_id=?", (attempt["run_id"],)
            ).fetchone()
            principal = json.loads(run[0])["principal_id"]
            next_state = "validated" if valid else "invalid"
            connection.execute(
                "INSERT INTO validations(attempt_id, run_id, envelope_id, valid, validator_ref, principal_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    attempt_id,
                    attempt["run_id"],
                    attempt["last_envelope_id"],
                    int(valid),
                    validator_ref,
                    principal,
                ),
            )
            record = json.loads(
                connection.execute(
                    "SELECT record_json FROM attempts WHERE attempt_id=?", (attempt_id,)
                ).fetchone()[0]
            )
            record["state"] = next_state
            connection.execute(
                "UPDATE attempts SET state=?, record_json=? WHERE attempt_id=?",
                (next_state, self._json(record), attempt_id),
            )

    def confirm_attempt_stopped(self, attempt_id, provider_thread_id):
        if not isinstance(provider_thread_id, str) or not provider_thread_id:
            raise StorageError("stop confirmation must identify the recorded child")
        with self._mutation() as connection:
            launch = connection.execute(
                "SELECT provider_thread_id, state FROM launches WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            attempt = connection.execute(
                "SELECT record_json, state FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if (
                launch is None
                or attempt is None
                or launch["provider_thread_id"] != provider_thread_id
            ):
                raise StorageError("stop confirmation does not match the launched child")
            if attempt["state"] not in {"validated", "invalid"}:
                raise StorageError(
                    "child can be released only after its return is machine-validated"
                )
            connection.execute(
                "UPDATE launches SET state='stopped' WHERE attempt_id=?", (attempt_id,)
            )
            connection.execute(
                "DELETE FROM workspace_reservations WHERE attempt_id=?", (attempt_id,)
            )

    def record_format_correction(self, source_envelope_id, correction_attempt_id):
        """Record at most one correction request while retaining its original report."""
        with self._mutation() as connection:
            lineage = connection.execute(
                "SELECT source_envelope_id, purpose FROM attempt_lineage WHERE attempt_id=?",
                (correction_attempt_id,),
            ).fetchone()
            if (
                lineage is None
                or lineage["purpose"] != "format_correction"
                or lineage["source_envelope_id"] != source_envelope_id
            ):
                raise StorageError("format correction must be a linked format_correction attempt")
            try:
                connection.execute(
                    "INSERT INTO format_corrections(source_envelope_id, attempt_id) VALUES (?, ?)",
                    (source_envelope_id, correction_attempt_id),
                )
            except sqlite3.IntegrityError as exc:
                raise StorageError(
                    "a worker return may receive only one format correction"
                ) from exc

    def begin_launch(self, attempt_id):
        self._set_launch_state(attempt_id, "starting")

    def record_launch_started(self, attempt_id, provider_thread_id):
        if not isinstance(provider_thread_id, str) or not provider_thread_id:
            raise StorageError("host start acknowledgement must include its actual child id")
        with self._mutation() as connection:
            row = connection.execute(
                "SELECT state FROM launches WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if row is None or row["state"] not in {"starting", "started"}:
                raise StorageError("launch must be marked starting before host acknowledgement")
            if row["state"] == "started":
                existing = connection.execute(
                    "SELECT provider_thread_id FROM launches WHERE attempt_id=?", (attempt_id,)
                ).fetchone()[0]
                if existing != provider_thread_id:
                    raise StorageError(
                        "launch acknowledgement conflicts with its recorded child id"
                    )
                return
            connection.execute(
                "UPDATE launches SET state='started', provider_thread_id=? WHERE attempt_id=?",
                (provider_thread_id, attempt_id),
            )
            connection.execute(
                "UPDATE attempts SET state='active' WHERE attempt_id=? AND state IN ('reserved', 'starting')",
                (attempt_id,),
            )
            row = connection.execute(
                "SELECT record_json FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row:
                record = json.loads(row[0])
                record["state"] = "active"
                record["provider_thread_id"] = provider_thread_id
                connection.execute(
                    "UPDATE attempts SET record_json=? WHERE attempt_id=?",
                    (self._json(record), attempt_id),
                )
            connection.execute(
                "UPDATE workspace_reservations SET state='active' WHERE attempt_id=?", (attempt_id,)
            )

    def record_launch_failed(self, attempt_id):
        with self._mutation() as connection:
            row = connection.execute(
                "SELECT state FROM launches WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if row is None or row["state"] not in {"reserved", "starting"}:
                raise StorageError("launch failure cannot be recorded after an acknowledgement")
            connection.execute(
                "UPDATE launches SET state='start_failed' WHERE attempt_id=?", (attempt_id,)
            )
            connection.execute(
                "UPDATE attempts SET state='start_failed' WHERE attempt_id=?", (attempt_id,)
            )
            row = connection.execute(
                "SELECT record_json FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row:
                record = json.loads(row[0])
                record["state"] = "start_failed"
                connection.execute(
                    "UPDATE attempts SET record_json=? WHERE attempt_id=?",
                    (self._json(record), attempt_id),
                )
            connection.execute(
                "DELETE FROM workspace_reservations WHERE attempt_id=?", (attempt_id,)
            )

    def _set_launch_state(self, attempt_id, state):
        with self._mutation() as connection:
            cursor = connection.execute(
                "UPDATE launches SET state=? WHERE attempt_id=? AND state='reserved'",
                (state, attempt_id),
            )
            if cursor.rowcount != 1:
                raise StorageError("launch is not reserved")
            connection.execute(
                "UPDATE attempts SET state='starting' WHERE attempt_id=? AND state='reserved'",
                (attempt_id,),
            )
            row = connection.execute(
                "SELECT record_json FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row:
                record = json.loads(row[0])
                record["state"] = "starting"
                connection.execute(
                    "UPDATE attempts SET record_json=? WHERE attempt_id=?",
                    (self._json(record), attempt_id),
                )
            connection.execute(
                "UPDATE workspace_reservations SET state='starting' WHERE attempt_id=?",
                (attempt_id,),
            )

    def reconcile_launch(self, idempotency_key, lookup=None):
        """Resolve a recorded launch key; unresolved starts remain reserved and cannot relaunch."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempt_id, provider_thread_id, state FROM launches WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            raise StorageError("unknown launch idempotency key")
        if row["provider_thread_id"]:
            return row["provider_thread_id"]
        if lookup is None:
            return None
        found = lookup(idempotency_key)
        if found:
            self.record_launch_started(row["attempt_id"], found)
            return found
        return None

    def capture_result(self, envelope, body, dedup_key, new_state, fail_before_commit=False):
        if not isinstance(body, bytes) or not isinstance(dedup_key, str) or not dedup_key:
            raise StorageError("body must be bytes and dedup_key must be non-empty")
        if hashlib.sha256(body).hexdigest() != envelope.get("body_sha256"):
            raise StorageError("envelope hash does not match raw bytes")
        errors = validate_record("envelope", envelope)
        if errors:
            raise StorageError("invalid envelope: " + "; ".join(errors))
        if envelope["kind"] not in {"answer", "report"}:
            raise StorageError("only an answer or report can complete a worker attempt")
        with self._mutation() as connection:
            attempt = connection.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?", (envelope["attempt_id"],)
            ).fetchone()
            if (
                attempt is None
                or attempt["run_id"] != envelope["run_id"]
                or attempt["task_id"] != envelope["task_id"]
            ):
                raise StorageError("envelope does not belong to an existing attempt")
            launch = connection.execute(
                "SELECT * FROM launches WHERE attempt_id = ?", (envelope["attempt_id"],)
            ).fetchone()
            if launch is None or launch["state"] != "started":
                raise StorageError("report has no acknowledged controller-owned launch")
            run = connection.execute(
                "SELECT record_json FROM runs WHERE run_id = ?", (envelope["run_id"],)
            ).fetchone()
            if run is None or envelope["captured_by"] != json.loads(run[0])["principal_id"]:
                raise StorageError("return capture principal does not match the run controller")
            attempt_record = json.loads(attempt["record_json"])
            if (
                envelope.get("selected_template") != attempt_record["selected_template"]
                or envelope.get("reply_to") != launch["dispatch_envelope_id"]
                or envelope.get("provider_thread_id") != launch["provider_thread_id"]
                or envelope.get("from") != "worker:" + attempt_record["selected_template"]
            ):
                raise StorageError(
                    "report does not match the selected template and dispatched launch"
                )
            if any(
                envelope.get(field) != attempt_record.get(field)
                for field in TEMPLATE_IDENTITY_FIELDS
            ):
                raise StorageError(
                    "report template provenance does not match the persisted attempt"
                )
            existing = connection.execute(
                "SELECT * FROM envelopes WHERE dedup_key = ?", (dedup_key,)
            ).fetchone()
            if existing:
                if existing["body_sha256"] == envelope["body_sha256"] and existing[
                    "record_json"
                ] == self._json(envelope):
                    return {
                        "status": "captured",
                        "envelope_id": existing["envelope_id"],
                        "replayed": True,
                    }
                # Preserve the contradictory raw result and block the governed run.
                connection.execute(
                    "INSERT INTO envelopes(envelope_id, run_id, task_id, attempt_id, dedup_key, body, body_sha256, source_metadata_json, record_json, correction_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        envelope["envelope_id"],
                        envelope["run_id"],
                        envelope["task_id"],
                        envelope["attempt_id"],
                        dedup_key,
                        body,
                        envelope["body_sha256"],
                        self._json(self._source_metadata(envelope)),
                        self._json(envelope),
                        existing["envelope_id"],
                    ),
                )
                connection.execute(
                    "UPDATE runs SET state = 'blocked' WHERE run_id = ?", (envelope["run_id"],)
                )
                self._append_event(connection, envelope, dedup_key, "conflicting_provider_result")
                return {
                    "status": "conflict",
                    "envelope_id": envelope["envelope_id"],
                    "original_envelope_id": existing["envelope_id"],
                }
            transition_errors = validate_attempt_transition(attempt["state"], new_state)
            if transition_errors:
                raise StorageError("; ".join(transition_errors))
            if fail_before_commit:
                raise StorageError("injected failure before commit")
            connection.execute(
                "INSERT INTO envelopes(envelope_id, run_id, task_id, attempt_id, dedup_key, body, body_sha256, source_metadata_json, record_json, correction_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    envelope["envelope_id"],
                    envelope["run_id"],
                    envelope["task_id"],
                    envelope["attempt_id"],
                    dedup_key,
                    body,
                    envelope["body_sha256"],
                    self._json(self._source_metadata(envelope)),
                    self._json(envelope),
                ),
            )
            connection.execute(
                "UPDATE attempts SET state = ?, last_envelope_id = ?, record_json = ? WHERE attempt_id = ?",
                (
                    new_state,
                    envelope["envelope_id"],
                    self._json(
                        {
                            **json.loads(attempt["record_json"]),
                            "state": new_state,
                            "last_envelope_id": envelope["envelope_id"],
                        }
                    ),
                    envelope["attempt_id"],
                ),
            )
            connection.execute(
                "UPDATE workspace_reservations SET state=? WHERE attempt_id=?",
                (new_state, envelope["attempt_id"]),
            )
            self._append_event(connection, envelope, dedup_key, "result_captured")
            return {"status": "captured", "envelope_id": envelope["envelope_id"], "replayed": False}

    @staticmethod
    def _source_metadata(envelope):
        return {
            field: envelope[field]
            for field in (
                "capture_source",
                "captured_by",
                "provider_thread_id",
                "provider_turn_id",
                "provider_event_id",
            )
        }

    def _append_event(self, connection, envelope, dedup_key, kind):
        connection.execute(
            "INSERT INTO events(run_id, task_id, attempt_id, dedup_key, kind, record_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                envelope["run_id"],
                envelope["task_id"],
                envelope["attempt_id"],
                dedup_key,
                kind,
                self._json({"kind": kind, "envelope_id": envelope["envelope_id"]}),
                envelope["created_at"],
            ),
        )

    def count(self, table):
        if table not in {
            "runs",
            "preflights",
            "tasks",
            "attempts",
            "envelopes",
            "events",
            "decisions",
            "workspace_reservations",
            "attempt_lineage",
            "format_corrections",
            "validations",
        }:
            raise ValueError("unknown table")
        with self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def attempt_state(self, attempt_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            return None if row is None else row[0]

    def run_state(self, run_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return None if row is None else row[0]

    def record_decision(self, run_id, decision_id, family, decision, attempt_id, principal_id):
        if family not in {"implementation", "specification", "quality"} or decision not in {
            "accept",
            "reject",
            "format_correction",
            "repair",
            "escalate",
        }:
            raise StorageError("decision family or value is unsupported")
        if not all(isinstance(value, str) and value for value in (attempt_id, principal_id)):
            raise StorageError("decision requires a linked attempt and principal")
        with self._mutation() as connection:
            attempt = connection.execute(
                "SELECT run_id, state, last_envelope_id FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            run = connection.execute(
                "SELECT record_json FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            validation = connection.execute(
                "SELECT valid, envelope_id, principal_id FROM validations WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or run is None or attempt["run_id"] != run_id:
                raise StorageError("decision attempt is missing or belongs to another run")
            if validation is None or (decision == "accept" and validation["valid"] != 1):
                raise StorageError("orchestrator decision requires a recorded machine validation")
            if decision == "accept" and attempt["state"] != "validated":
                raise StorageError("acceptance requires a machine-validated attempt")
            if validation["envelope_id"] != attempt["last_envelope_id"]:
                raise StorageError("decision evidence is not the validated return")
            expected_prefix = {
                "implementation": "impl-",
                "specification": "spec-",
                "quality": "quality-",
            }[family]
            launch = connection.execute(
                "SELECT a.record_json FROM attempts a WHERE a.attempt_id=?", (attempt_id,)
            ).fetchone()
            selected_template = json.loads(launch[0])["selected_template"]
            if not selected_template.startswith(expected_prefix):
                raise StorageError("decision family does not match the attempted worker role")
            run_principal = json.loads(run[0])["principal_id"]
            if principal_id != run_principal or principal_id != validation["principal_id"]:
                raise StorageError(
                    "decision principal does not match the recorded controller principal"
                )
            record = {
                "decision_id": decision_id,
                "family": family,
                "decision": decision,
                "attempt_id": attempt_id,
                "evidence_ref": validation["envelope_id"],
                "principal_id": principal_id,
            }
            connection.execute(
                "INSERT INTO decisions(decision_id, run_id, attempt_id, record_json) VALUES (?, ?, ?, ?)",
                (decision_id, run_id, attempt_id, self._json(record)),
            )

    def validate_accepted_outcome(self, outcome, controller_principal, captured_evidence_refs):
        """Validate all accepted-outcome references against records in this store."""
        with self._connect() as connection:
            decisions = {}
            for row in connection.execute(
                "SELECT decision_id, record_json FROM decisions WHERE run_id=?",
                (outcome.get("run_id"),),
            ):
                decisions[row["decision_id"]] = json.loads(row["record_json"])
            attempts = {
                row["attempt_id"]: row
                for row in connection.execute(
                    "SELECT attempt_id, run_id, state, last_envelope_id FROM attempts WHERE run_id=?",
                    (outcome.get("run_id"),),
                )
            }
            evidence = {
                row["envelope_id"]
                for row in connection.execute(
                    "SELECT envelope_id FROM envelopes WHERE run_id=?", (outcome.get("run_id"),)
                )
            }
            run_row = connection.execute(
                "SELECT record_json FROM runs WHERE run_id=?", (outcome.get("run_id"),)
            ).fetchone()
            catalog_row = connection.execute(
                "SELECT catalog_sha256, catalog_json FROM run_template_catalogs WHERE run_id=?",
                (outcome.get("run_id"),),
            ).fetchone()
        if run_row is None:
            return ["accepted outcome references an unknown run"]
        if catalog_row is None:
            return ["accepted outcome run has no persisted template catalog"]
        catalog = json.loads(catalog_row["catalog_json"])
        if catalog_row["catalog_sha256"] != catalog.get("catalog_sha256"):
            return ["accepted outcome run has inconsistent template catalog identity"]
        run_principal = json.loads(run_row[0])["principal_id"]
        required_families = {"implementation", "specification", "quality"}
        referenced_decisions = outcome.get("orchestrator_decision_refs", [])
        decision_records = [decisions[ref] for ref in referenced_decisions if ref in decisions]
        accepted_families = {
            item["family"] for item in decision_records if item["decision"] == "accept"
        }
        if not required_families.issubset(accepted_families):
            return [
                "accepted outcome requires implementation, specification, and quality decisions"
            ]
        errors = validate_outcome(
            outcome,
            controller_principal,
            set(captured_evidence_refs).intersection(evidence),
            {catalog_row["catalog_sha256"]: catalog},
        )
        if errors:
            return errors
        if not set(outcome["validated_attempt_refs"]).issubset(attempts):
            return ["accepted outcome references an unknown or unrelated attempt"]
        if any(attempts[ref]["state"] != "validated" for ref in outcome["validated_attempt_refs"]):
            return ["accepted outcome references an attempt that is not machine-validated"]
        if not set(outcome["orchestrator_decision_refs"]).issubset(decisions):
            return ["accepted outcome references a missing orchestrator decision"]
        if {item.get("attempt_id") for item in decision_records} != set(
            outcome["validated_attempt_refs"]
        ):
            return ["accepted outcome decisions are not linked to exactly its validated attempts"]
        if any(item.get("principal_id") != run_principal for item in decision_records):
            return ["accepted outcome includes a decision from a different principal"]
        if any(
            attempts[item["attempt_id"]]["last_envelope_id"] != item.get("evidence_ref")
            for item in decision_records
        ):
            return ["accepted outcome decision does not reference its attempt's validated evidence"]
        if not {item["evidence_ref"] for item in decision_records}.issubset(
            set(captured_evidence_refs)
        ):
            return ["accepted outcome decision evidence is not controller-captured"]
        return []

    def export(self, destination, fail_after=None):
        """Generate disposable exports; this method never reads existing exports."""
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            runs = [
                json.loads(row[0])
                for row in connection.execute("SELECT record_json FROM runs ORDER BY run_id")
            ]
            attempts = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT record_json FROM attempts ORDER BY attempt_id"
                )
            ]
            payload = {"schema_version": SCHEMA_VERSION, "runs": runs, "attempts": attempts}
        json_path = destination / "runtime.json"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if fail_after == "json":
            raise OSError("injected partial export")
        lines = ["# Runtime export", "", "## Runs", ""] + [
            "- %s: %s" % (run["run_id"], run["state"]) for run in runs
        ]
        (destination / "runtime.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
