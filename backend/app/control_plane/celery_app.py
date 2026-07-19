from __future__ import annotations

from .config import DeploymentProfile, PlatformSettings


def build_celery_app(settings: PlatformSettings | None = None):
    settings = settings or PlatformSettings.from_env()
    if settings.profile is not DeploymentProfile.TEAM:
        raise RuntimeError("Celery is only available in the team profile")
    try:
        from celery import Celery
    except ImportError as exc:
        raise RuntimeError("team profile requires the 'team' dependency extra") from exc
    app = Celery("code_research_agent", broker=settings.celery_broker_url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        enable_utc=True,
        timezone="UTC",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": 8 * 60 * 60},
        result_expires=3600,
        task_routes={
            "cra.analysis": {"queue": "cra.analysis"},
            "cra.indexing": {"queue": "cra.indexing"},
            "cra.research": {"queue": "cra.research"},
            "cra.alignment": {"queue": "cra.alignment"},
            "cra.evaluation": {"queue": "cra.evaluation"},
            "cra.replay": {"queue": "cra.replay"},
            "cra.export": {"queue": "cra.export"},
            "cra.backup": {"queue": "cra.backup"},
            "cra.restore": {"queue": "cra.restore"},
            "cra.maintenance": {"queue": "cra.maintenance"},
            "cra.delete": {"queue": "cra.maintenance"},
        },
    )
    return app
