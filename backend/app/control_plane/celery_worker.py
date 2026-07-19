from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .celery_app import build_celery_app


class TaskEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    attempt_id: str
    attempt_number: int = Field(ge=1)
    job_type: str
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_schema_version: int = Field(ge=1)
    message_deduplication_key: str = Field(pattern=r"^[0-9a-f]{64}$")


app = build_celery_app()


try:
    from celery.signals import worker_ready

    @worker_ready.connect
    def register_worker(**_kwargs) -> None:
        from .team_worker import TeamWorker

        TeamWorker.from_env().register()
except ImportError:  # pragma: no cover - Team dependencies are optional in Local profile
    pass


@app.task(name="cra.execute_job", bind=True, ignore_result=True)
def execute_job(self, envelope: dict) -> None:
    """A broker message is only a wake-up/correlation envelope; DB claim is authoritative."""
    validated = TaskEnvelope.model_validate(envelope)
    from .team_worker import TeamWorker

    TeamWorker.from_env().execute(validated, celery_task_id=self.request.id)
