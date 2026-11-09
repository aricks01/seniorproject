"""In-memory async job manager for the long-running operations (detect, crack).

Each job runs in its own daemon thread. The worker stores the live subprocess
handle so cancel() can terminate the tool. Jobs are kept in a dict keyed by id;
this is per-process state and resets when the server restarts — fine for a
single-host tool, not for a clustered deployment.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    kind: str                      # "detect" | "crack"
    state: str = "queued"          # queued -> running -> done/failed/cancelled
    result: dict[str, Any] = field(default_factory=dict)
    detail: str | None = None      # error message when failed
    progress: float | None = None  # live percent while running (0-100)
    _proc_sink: dict = field(default_factory=dict)   # holds live Popen
    _cancelled: bool = False

    def view(self) -> dict:
        """Serialize to the JSON shape common.js expects when polling."""
        out: dict[str, Any] = {"job_id": self.id, "state": self.state}
        if self.progress is not None and "percent" not in self.result:
            out["percent"] = round(self.progress)
        out.update(self.result)
        if self.detail:
            out["detail"] = self.detail
        return out


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def submit(self, kind: str, work: Callable[[Job], dict]) -> Job:
        """Register a job and run `work(job)` in a background thread.

        `work` returns the dict to merge into job.result on success, or raises.
        """
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job

        def runner() -> None:
            job.state = "running"
            try:
                result = work(job)
                if job._cancelled:
                    job.state = "cancelled"
                else:
                    job.result = result
                    job.state = "done"
            except Exception as e:  # noqa: BLE001 - surface any tool failure
                if job._cancelled:
                    job.state = "cancelled"
                else:
                    job.state = "failed"
                    job.detail = str(e)

        threading.Thread(target=runner, daemon=True).start()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        job._cancelled = True
        proc = job._proc_sink.get("proc")
        if proc and proc.poll() is None:
            proc.terminate()
        return True


jobs = JobManager()
