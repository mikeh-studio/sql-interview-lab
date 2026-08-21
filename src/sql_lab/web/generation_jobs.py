"""Thread-safe state for progressive background generation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from time import perf_counter
from uuid import uuid4


@dataclass
class GenerationJob:
    request_metadata: dict[str, object]
    id: str = field(default_factory=lambda: uuid4().hex[:16])
    status: str = "running"
    events: list[dict[str, object]] = field(default_factory=list)
    partial_result: dict[str, object] | None = None
    result: dict[str, object] | None = None
    telemetry: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    _started_at: float = field(default_factory=perf_counter, repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def add_event(
        self, stage: str, message: str, metadata: dict[str, object] | None = None
    ) -> dict[str, object]:
        with self._lock:
            event = {
                "sequence": len(self.events) + 1,
                "stage": stage,
                "message": message,
                "elapsed_seconds": round(perf_counter() - self._started_at, 3),
                "metadata": metadata or {},
            }
            self.events.append(event)
            return deepcopy(event)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return deepcopy(
                {
                    "generation_id": self.id,
                    "status": self.status,
                    "elapsed_seconds": round(perf_counter() - self._started_at, 3),
                    "events": self.events,
                    "partial_result": self.partial_result,
                    "result": self.result,
                    "telemetry": self.telemetry,
                    "error": self.error,
                }
            )


class GenerationJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, GenerationJob] = {}
        self._lock = RLock()

    def create(self, metadata: dict[str, object]) -> GenerationJob:
        job = GenerationJob(metadata)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > 100:
                completed = [
                    job_id
                    for job_id, candidate in self._jobs.items()
                    if candidate.status != "running"
                ]
                for job_id in completed[: len(self._jobs) - 100]:
                    self._jobs.pop(job_id, None)
        return job

    def get(self, generation_id: str) -> GenerationJob | None:
        with self._lock:
            return self._jobs.get(generation_id)

    def has_running(self) -> bool:
        with self._lock:
            return any(job.status == "running" for job in self._jobs.values())
