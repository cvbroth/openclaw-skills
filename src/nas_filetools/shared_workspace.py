"""Per-Agent registries over shared workspace subdirectories; one global heavy-worker slot."""
import json
import threading
import time
from dataclasses import replace
from pathlib import Path

from .contracts import Fault, Limits, owner
from .store import Store
from .worker import Supervisor


def mapped_store(profile, agent, limits, role="worker"):
    key = "service_root" if role == "worker" else "workspace"
    root = Path(profile[key]) if role == "worker" else Path(profile[key])/"filetools"
    if not root.is_absolute() or not Path(profile["workspace"]).is_absolute():
        raise Fault("ABSOLUTE_WORKSPACE_MAPPING_REQUIRED")
    sources = profile.get("processing_roots", {}) if role == "worker" else profile.get("source_roots", {})
    if role == "gateway":
        sources = {"workspace": {"path": profile["workspace"], "kind": "workspace"}, **sources}
    return Store(root, replace(limits, enabled_agents=(agent,), workspace_mode=True,
                              gateway_workspace=profile["workspace"], source_roots=sources))


class WorkspaceHub:
    def __init__(self, root, limits, profiles):
        self.root, self.limits, self.lock = Path(root), limits, threading.RLock()
        self.heavy_gate = threading.RLock()
        if set(profiles) != set(limits.enabled_agents):
            raise Fault("ENABLED_AGENT_MAPPING_MISMATCH")
        paths = [str(Path(p["service_root"]).resolve()) for p in profiles.values()]
        if len(set(paths)) != len(paths):
            raise Fault("AGENT_WORKSPACE_OVERLAP")
        for left in paths:
            if any(left != right and Path(left).is_relative_to(Path(right)) for right in paths):
                raise Fault("AGENT_WORKSPACE_OVERLAP")
        self.stores = {agent: mapped_store(profile, agent, limits) for agent, profile in profiles.items()}

    def for_identity(self, identity):
        owner(identity)
        if identity["agent_id"] not in self.stores:
            raise Fault("FORBIDDEN")
        return self.stores[identity["agent_id"]]

    def agent(self, identity):
        return self.for_identity(identity).agent(identity)

    def cleanup(self):
        return {agent: store.cleanup() for agent, store in self.stores.items()}


class WorkspaceSupervisor:
    def __init__(self, hub):
        self.hub = hub
        self.workers = {agent: Supervisor(store) for agent, store in hub.stores.items()}
        for worker in self.workers.values():
            with worker.store.db() as db:
                for product in db.execute("SELECT id,info FROM files WHERE mode='artifact' AND state='PUBLISHED'").fetchall():
                    identifier = json.loads(product["info"]).get("job_id")
                    job = db.execute("SELECT status FROM jobs WHERE id=?", (identifier,)).fetchone()
                    if not job or job[0] not in ("SUCCEEDED", "PARTIAL"):
                        db.execute("UPDATE files SET state='REJECTED' WHERE id=?", (product["id"],))

    @property
    def processes(self):
        return {key: value for worker in self.workers.values() for key, value in worker.processes.items()}

    def tick(self):
        with self.hub.heavy_gate:
            self._tick()

    def _tick(self):
        for worker in self.workers.values():
            worker.tick(can_start=False)
        if self.processes:
            return
        candidates = []
        for agent, worker in self.workers.items():
            with worker.store.db() as db:
                row = db.execute("SELECT created FROM jobs WHERE status='QUEUED' ORDER BY created LIMIT 1").fetchone()
            if row:
                candidates.append((row[0], agent))
        if candidates:
            self.workers[min(candidates)[1]].tick(can_start=True)

    def close(self):
        for worker in self.workers.values():
            worker.close()


def management_call(configuration, identity, operation, params):
    raw = json.loads(Path(configuration).read_text(encoding="utf-8"))
    owner(identity)
    profile = raw.get("workspaces", {}).get(identity["agent_id"])
    if not profile:
        raise Fault("FORBIDDEN")
    limits = Limits(**{**raw.get("limits", {}), "enabled_agents": tuple(raw["workspaces"])})
    store = mapped_store(profile, identity["agent_id"], limits, "gateway")
    if operation in ("touch_path", "lease_path", "finish_access"):
        from .contracts import strict
        from .management import public_reference
        strict(params, ("path", "token", "success"), ("path",))
        if operation != "touch_path" and (not isinstance(params.get("token"), str) or not 1 <= len(params["token"]) <= 200):
            raise Fault("INVALID_PARAMETERS")
        target = Path(params["path"])
        if not target.is_absolute():
            target = Path(profile["workspace"])/target
        with store.lock, store.db() as db:
            jobs = db.execute("SELECT * FROM jobs WHERE owner=? AND status IN ('SUCCEEDED','PARTIAL')", (owner(identity),)).fetchall()
            for job in jobs:
                if job["expires"] <= time.time() and operation != "finish_access":
                    continue
                for artifact in store.manifest(dict(job))["artifacts"]:
                    path = store.task(job["id"])/artifact["file"]
                    # Match lexical managed paths; never follow a user-supplied symlink to grant access.
                    reference = public_reference(store, path)
                    if str(target.absolute()) == str(Path(reference["gateway_path"]).absolute()) and path.is_file() and not path.is_symlink():
                        if operation == "lease_path":
                            db.execute("INSERT OR REPLACE INTO access_leases VALUES(?,?,?)", (job["id"], params["token"], time.time()+300))
                        elif operation == "finish_access":
                            db.execute("DELETE FROM access_leases WHERE job_id=? AND token=?", (job["id"], params["token"]))
                            if params.get("success") is True:
                                db.execute("UPDATE jobs SET expires=? WHERE id=?", (time.time()+store.limits.ttl_seconds, job["id"]))
                        else:
                            store.touch(job["id"])
                        return {"status": "LEASED" if operation == "lease_path" else "TOUCHED", "job_id": job["id"], "artifact_id": artifact["artifact_id"]}
        return {"status": "NOT_TOUCHED"}
    if operation in ("register", "register_media"):
        from .management import register_source
        return register_source(store, identity, params, trusted_media=operation == "register_media")
    if operation != "files":
        raise Fault("MANAGEMENT_OPERATION_DENIED")
    from .service import dispatch
    return dispatch(store, identity, operation, params)
