from __future__ import annotations

from .schemas import JobRecord, WorkerRegistration


def worker_can_execute(
    worker: WorkerRegistration, job: JobRecord, *, database_schema_version: int,
) -> bool:
    return (
        job.job_type in worker.supported_job_types
        and job.queue_name in worker.queue_names
        and worker.min_task_schema_version <= job.task_schema_version <= worker.max_task_schema_version
        and worker.min_database_schema_version
        <= database_schema_version
        <= worker.max_database_schema_version
        and worker.handler_versions.get(job.job_type) == job.handler_version
    )


def select_compatible_workers(
    workers: list[WorkerRegistration], job: JobRecord, *, database_schema_version: int,
) -> list[WorkerRegistration]:
    return [
        worker for worker in workers
        if worker_can_execute(worker, job, database_schema_version=database_schema_version)
    ]

