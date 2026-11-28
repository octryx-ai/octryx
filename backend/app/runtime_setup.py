from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.worker_pool.scaling import WorkerPoolAutoscaler

from .bootstrap import seed_database
from .config import get_settings
from .db.startup import ensure_runtime_database_ready
from .plugins import plugin_manager
from .runtime_toggles import (
    background_workers_enabled,
    knowledge_projection_enabled,
    knowledge_source_sync_scheduler_enabled,
    skip_chat_build_enabled,
)
from .scheduler import TaskScheduler
from .services.analytics.service import AnalyticsWorker
from .services.approval.stale_expiry import StaleApprovalExpiryWorker
from .services.browser_automation import browser_automation_manager
from .services.channel_config.runtime_sync import ChannelReconciler
from .services.channel_router_runtime import channel_message_router
from .services.connector_health import ConnectorHealthWorker
from .services.connector_test_service import run_connector_connection_test
from .services.data_access import platform_maintenance
from .services.decisions.flusher import decision_flusher
from .services.durable_process_runtime import configure_durable_process_runtime
from .services.inbound_alerts.change_poller import ChangeSourcePollWorker
from .services.interactive_python import interactive_python_manager
from .services.knowledge.projection.worker import KnowledgeProjectionWorker
from .services.knowledge.retention.scheduled import KnowledgeRetentionReconcileWorker
from .services.knowledge.sources.sync.scheduler import KnowledgeSourceSyncScheduler
from .services.lsp import lsp_manager
from .services.mobile.push import MobilePushSweeper
from .services.notification_delivery import NotificationDeliveryWorker
from .services.observability import _HTTP_REQUEST_COUNTER, render_prometheus_metrics, run_platform_health_checks
from .services.observability.health_checks import evaluate_platform_health_summary
from .services.outbound_webhook import OutboundWebhookWorker
from .services.persistent_process_runtime import configure_persistent_process_runtime
from .services.pr_review_bot.worker import PrReviewSyncWorker
from .services.privacy import RetentionWorker
from .services.problems.alerts import ProblemAlertWorker
from .services.pty import pty_manager
from .services.runtime_ownership.worker import RuntimeOwnershipWorker
from .services.secret import SecretExpiryWorker
from .services.secure_work.pull_requests.refresh_worker import PullRequestRefreshWorker
from .services.session.remote_stop import RemoteTurnStopWatcher
from .services.session.workspace import SessionWorkspaceCleanupWorker
from .services.skill_catalog.upstream_worker import SkillUpstreamWorker
from .services.sla import SLAMonitorWorker
from .services.worker import refresh_all_workers_on_startup
from .services.worker_monitor_service import WorkerMonitorWorker
from .services.worker_reporting import WorkerReportWorker
from .services.worker_shift_service import WorkerAgendaWorker
from .services.workflow_runs.review.runner import ReviewWorker
from .services.workflow_runs.sweep import WorkflowRunSweepWorker
from .services.workflow_runs.watch import WatchPollWorker

logger = logging.getLogger(__name__)
STARTUP_REASON = "startup: seeding and init_db"
WORKERS_REASON = "platform background workers: queues, schedules, sweeps and pollers of every Workspace"


async def _seed_as_platform(db) -> None:
    async with platform_maintenance(STARTUP_REASON):
        await seed_database(db)


STATIC_DIR = (Path(__file__).parent / "web" / "static").resolve()
REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_FRONTEND_DIR = (REPO_ROOT / "frontend" / "chat").resolve()
CHAT_FRONTEND_BUILD_DIR = (STATIC_DIR / "chat").resolve()


def _chat_frontend_build_missing() -> bool:
    return not (CHAT_FRONTEND_BUILD_DIR / "index.html").exists()


def _chat_frontend_sources_newer_than_build() -> bool:
    build_index = CHAT_FRONTEND_BUILD_DIR / "index.html"
    if not build_index.exists():
        return True
    build_mtime = build_index.stat().st_mtime
    for relative in (
        "src",
        "public",
        "package.json",
        "package-lock.json",
        "vite.config.ts",
        "tsconfig.json",
        "index.html",
    ):
        candidate = CHAT_FRONTEND_DIR / relative
        if not candidate.exists():
            continue
        if candidate.is_file():
            if candidate.stat().st_mtime > build_mtime:
                return True
            continue
        for path in candidate.rglob("*"):
            if path.is_file() and path.stat().st_mtime > build_mtime:
                return True
    return False


def ensure_chat_frontend_built() -> None:
    if skip_chat_build_enabled():
        logger.info("Skipping chat frontend build because OCTRYX_SKIP_CHAT_BUILD is enabled")
        return
    if not CHAT_FRONTEND_DIR.exists():
        logger.warning("Chat frontend directory does not exist", extra={"path": str(CHAT_FRONTEND_DIR)})
        return
    if not (_chat_frontend_build_missing() or _chat_frontend_sources_newer_than_build()):
        return

    logger.info("Building chat frontend", extra={"path": str(CHAT_FRONTEND_DIR)})
    try:
        subprocess.run(["npm", "install"], cwd=CHAT_FRONTEND_DIR, check=True)
        subprocess.run(["npm", "run", "build"], cwd=CHAT_FRONTEND_DIR, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Chat frontend build requires npm, but npm was not found in PATH. "
            "Install Node.js/npm or set OCTRYX_SKIP_CHAT_BUILD=1 to skip the automatic build."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Chat frontend build failed with exit code {exc.returncode}") from exc


HEALTH_LOOP_SECONDS = 30.0


async def _register_bundled_litellm(db: AsyncSession) -> None:
    # A LiteLLM that is not up yet never stops the start; the next start registers it.
    from .services.model_gateway.bundled_litellm import register_bundled_provider

    try:
        await register_bundled_provider(db)
    except Exception:
        await db.rollback()
        logger.exception("The bundled LiteLLM provider could not be registered")


@dataclass(slots=True)
class PlatformRuntime:
    async_session_factory: object
    task_scheduler: TaskScheduler
    retention_worker: RetentionWorker
    notification_delivery_worker: NotificationDeliveryWorker
    outbound_webhook_worker: OutboundWebhookWorker
    connector_health_worker: ConnectorHealthWorker
    analytics_worker: AnalyticsWorker
    knowledge_projection_worker: KnowledgeProjectionWorker
    worker_monitor_worker: WorkerMonitorWorker
    worker_agenda_worker: WorkerAgendaWorker
    worker_report_worker: WorkerReportWorker
    worker_pool_worker: WorkerPoolAutoscaler
    sla_monitor_worker: SLAMonitorWorker
    secret_expiry_worker: SecretExpiryWorker
    session_workspace_cleanup_worker: SessionWorkspaceCleanupWorker
    # Always started: holds this process's liveness lease and settles orphaned turns.
    runtime_ownership_worker: RuntimeOwnershipWorker
    # Started only when OCTRYX_ENABLE_KNOWLEDGE_SOURCE_SYNC_SCHEDULER is on (default off).
    knowledge_source_sync_scheduler: KnowledgeSourceSyncScheduler | None = None
    # Expires stale pending approvals; idle when approval_pending_ttl_hours is 0.
    stale_approval_expiry_worker: StaleApprovalExpiryWorker | None = None
    # Reconciles every Workspace with a knowledge retention policy (report-only), daily by default.
    knowledge_retention_reconcile_worker: KnowledgeRetentionReconcileWorker | None = None
    # Reminds and times out waiting workflow-run nodes.
    workflow_run_sweep_worker: WorkflowRunSweepWorker | None = None
    # The poll fallback of watched external states (PR, CI, Jira) every 5 minutes.
    workflow_run_watch_worker: WatchPollWorker | None = None
    # Recorded pull requests read from their host: open ones every 15 minutes, requested ones next minute.
    pull_request_refresh_worker: PullRequestRefreshWorker | None = None
    workflow_run_review_worker: ReviewWorker | None = None
    # The PR review bot's hourly pull request sync (repositories with the bot's sync trigger on).
    pr_review_sync_worker: PrReviewSyncWorker | None = None
    # Skill catalog scheduled upstream check; interval from the catalog settings.
    skill_upstream_worker: SkillUpstreamWorker | None = None
    # Jira/ServiceNow changes as an inbound webhook source (read every 5 minutes).
    change_source_poll_worker: ChangeSourcePollWorker | None = None
    # Always started: this process's channels follow the channel_configs rows.
    channel_reconciler: ChannelReconciler | None = None
    # Always started: cancels local turns another process was asked to stop.
    remote_stop_watcher: RemoteTurnStopWatcher | None = None
    # Octryx Mobile: notifications on paired phones (idle while push is not configured).
    mobile_push_sweeper: MobilePushSweeper | None = None
    # run and device-job problems announced to Workspace admins, channels and webhooks.
    problem_alert_worker: ProblemAlertWorker | None = None
    _background_workers_started: bool = field(default=False, init=False)
    _health_loop_task: asyncio.Task | None = field(default=None, init=False)
    _knowledge_projection_started: bool = field(default=False, init=False)
    _source_sync_scheduler_started: bool = field(default=False, init=False)
    _channel_router_started: bool = field(default=False, init=False)

    async def startup(self) -> None:
        ensure_chat_frontend_built()
        # The schema comes first: the maintenance audit row needs its table.
        await ensure_runtime_database_ready(self.async_session_factory, seed_database=_seed_as_platform)
        async with platform_maintenance(STARTUP_REASON):
            await self._prepare_database()
        async with platform_maintenance(WORKERS_REASON):
            await self._start_workers()

    async def _prepare_database(self) -> None:
        async with self.async_session_factory() as db:
            if background_workers_enabled():
                refreshed_workers = await refresh_all_workers_on_startup(db)
                logger.info("Worker startup refresh completed", extra={"workers_refreshed": refreshed_workers})
            # Reset circuit breakers on startup so stale errors from previous
            # deployments do not block connector tools indefinitely.
            try:
                from sqlalchemy import text as _text

                await db.execute(
                    _text(
                        "UPDATE circuit_breaker_states "
                        "SET state='closed', failure_count=0, last_error=NULL, next_retry_at=NULL "
                        "WHERE state != 'closed'"
                    )
                )
                await db.commit()
                logger.info("Circuit breakers reset on startup")
            except Exception:
                pass
            await _register_bundled_litellm(db)
        await self._sync_image_plugins()

    async def _start_workers(self) -> None:
        workers_enabled = background_workers_enabled()
        await self.runtime_ownership_worker.start()
        if self.remote_stop_watcher is not None:
            await self.remote_stop_watcher.start()
        decision_flusher.start()
        await self._initialize_channels()

        if workers_enabled:
            self._background_workers_started = True
            await self._start_background_workers(knowledge_projection_enabled=knowledge_projection_enabled())
            if self.mobile_push_sweeper is not None:
                await self.mobile_push_sweeper.start()
            self._health_loop_task = asyncio.create_task(self._health_loop(), name="platform-health-loop")

    async def _sync_image_plugins(self) -> None:
        from .runtime_toggles import SKIP_IMAGE_PLUGINS_ENV, env_flag
        from .services.plugins.image import sync_image_plugins

        if env_flag(SKIP_IMAGE_PLUGINS_ENV):
            return
        try:
            await sync_image_plugins(self.async_session_factory)
        except Exception:  # noqa: BLE001
            logger.exception("Image plugins could not be synced")

    async def _health_loop(self) -> None:
        while True:
            try:
                await self.health_checks(app_version="")
            except Exception:  # noqa: BLE001 - the next round tries again
                logger.warning("Platform health loop round failed", exc_info=True)
            await asyncio.sleep(HEALTH_LOOP_SECONDS)

    async def shutdown(self) -> None:
        if self._health_loop_task is not None:
            self._health_loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._health_loop_task
            self._health_loop_task = None
        await self.runtime_ownership_worker.stop()
        if self.remote_stop_watcher is not None:
            await self.remote_stop_watcher.stop()
        if self.mobile_push_sweeper is not None:
            await self.mobile_push_sweeper.stop()
        await decision_flusher.stop()
        if self._background_workers_started:
            await self._stop_background_workers()
            self._background_workers_started = False
        await self._stop_channels()

        from .services.model_gateway.inbound.seat_upstream import close_seat_clients

        await close_seat_clients()  # the pooled seat upstream clients (one per upstream and loop)
        await browser_automation_manager.stop_all()
        await interactive_python_manager.stop_all()
        await lsp_manager.stop_all()
        pty_manager.stop_all()
        await plugin_manager.stop_all()

    async def health_checks(self, *, app_version: str) -> dict[str, object]:
        checks = await run_platform_health_checks(
            self.async_session_factory,
            task_scheduler=self.task_scheduler,
            channel_router=channel_message_router,
            retention_worker=self.retention_worker,
            outbound_webhook_worker=self.outbound_webhook_worker,
            connector_health_worker=self.connector_health_worker,
            analytics_worker=self.analytics_worker,
            worker_monitor_worker=self.worker_monitor_worker,
            worker_agenda_worker=self.worker_agenda_worker,
            worker_report_worker=self.worker_report_worker,
            worker_pool_worker=self.worker_pool_worker,
            sla_monitor_worker=self.sla_monitor_worker,
            secret_expiry_worker=self.secret_expiry_worker,
            session_workspace_cleanup_worker=self.session_workspace_cleanup_worker,
        )
        summary = evaluate_platform_health_summary(checks)
        return {
            "status": summary["status"],
            "version": app_version,
            "summary": summary,
            "checks": checks,
            "configuration": {"security_defaults": get_settings().security_defaults_report()},
        }

    async def metrics_payload(self) -> str:
        return await render_prometheus_metrics(
            self.async_session_factory,
            task_scheduler=self.task_scheduler,
            channel_router=channel_message_router,
            retention_worker=self.retention_worker,
            outbound_webhook_worker=self.outbound_webhook_worker,
            connector_health_worker=self.connector_health_worker,
            analytics_worker=self.analytics_worker,
            worker_monitor_worker=self.worker_monitor_worker,
            worker_agenda_worker=self.worker_agenda_worker,
            worker_report_worker=self.worker_report_worker,
            worker_pool_worker=self.worker_pool_worker,
            sla_monitor_worker=self.sla_monitor_worker,
            secret_expiry_worker=self.secret_expiry_worker,
            session_workspace_cleanup_worker=self.session_workspace_cleanup_worker,
            request_counter=_HTTP_REQUEST_COUNTER,
        )

    async def _initialize_channels(self) -> None:
        if self.channel_reconciler is None:
            self.channel_reconciler = ChannelReconciler(self.async_session_factory)
        await self.channel_reconciler.reconcile_once()
        await channel_message_router.start(self.async_session_factory)
        self._channel_router_started = True
        await self.channel_reconciler.start()

    async def _stop_channels(self) -> None:
        if self.channel_reconciler is not None:
            await self.channel_reconciler.stop()
        if self._channel_router_started:
            await channel_message_router.stop()
            self._channel_router_started = False

    async def _start_background_workers(self, *, knowledge_projection_enabled: bool) -> None:
        await self.task_scheduler.start()
        await self.retention_worker.start()
        await self.notification_delivery_worker.start()
        await self.outbound_webhook_worker.start()
        await self.connector_health_worker.start()
        await self.analytics_worker.start()
        if knowledge_projection_enabled:
            await self.knowledge_projection_worker.start()
            self._knowledge_projection_started = True
        if self.knowledge_source_sync_scheduler is not None and knowledge_source_sync_scheduler_enabled():
            await self.knowledge_source_sync_scheduler.start()
            self._source_sync_scheduler_started = True
        if self.stale_approval_expiry_worker is not None:
            await self.stale_approval_expiry_worker.start()
        if self.knowledge_retention_reconcile_worker is not None:
            await self.knowledge_retention_reconcile_worker.start()
        if self.workflow_run_sweep_worker is not None:
            await self.workflow_run_sweep_worker.start()
        if self.workflow_run_watch_worker is not None:
            await self.workflow_run_watch_worker.start()
        if self.pull_request_refresh_worker is not None:
            await self.pull_request_refresh_worker.start()
        if self.workflow_run_review_worker is not None:
            await self.workflow_run_review_worker.start()
        if self.pr_review_sync_worker is not None:
            await self.pr_review_sync_worker.start()
        await self.worker_monitor_worker.start()
        await self.worker_agenda_worker.start()
        await self.worker_report_worker.start()
        await self.worker_pool_worker.start()
        await self.sla_monitor_worker.start()
        if self.problem_alert_worker is not None:
            await self.problem_alert_worker.start()
        await self.secret_expiry_worker.start()
        await self.session_workspace_cleanup_worker.start()
        if self.skill_upstream_worker is not None:
            await self.skill_upstream_worker.start()
        if self.change_source_poll_worker is not None:
            await self.change_source_poll_worker.start()

    async def _stop_background_workers(self) -> None:
        if self.change_source_poll_worker is not None:
            await self.change_source_poll_worker.stop()
        self.task_scheduler.shutdown()
        await self.retention_worker.stop()
        await self.notification_delivery_worker.stop()
        await self.outbound_webhook_worker.stop()
        await self.connector_health_worker.stop()
        await self.analytics_worker.stop()
        if self._knowledge_projection_started:
            await self.knowledge_projection_worker.stop()
            self._knowledge_projection_started = False
        if self._source_sync_scheduler_started and self.knowledge_source_sync_scheduler is not None:
            await self.knowledge_source_sync_scheduler.stop()
            self._source_sync_scheduler_started = False
        if self.stale_approval_expiry_worker is not None:
            await self.stale_approval_expiry_worker.stop()
        if self.knowledge_retention_reconcile_worker is not None:
            await self.knowledge_retention_reconcile_worker.stop()
        if self.workflow_run_sweep_worker is not None:
            await self.workflow_run_sweep_worker.stop()
        if self.workflow_run_watch_worker is not None:
            await self.workflow_run_watch_worker.stop()
        if self.pull_request_refresh_worker is not None:
            await self.pull_request_refresh_worker.stop()
        if self.workflow_run_review_worker is not None:
            await self.workflow_run_review_worker.stop()
        if self.pr_review_sync_worker is not None:
            await self.pr_review_sync_worker.stop()
        await self.worker_monitor_worker.stop()
        await self.worker_agenda_worker.stop()
        await self.worker_report_worker.stop()
        await self.worker_pool_worker.stop()
        await self.sla_monitor_worker.stop()
        if self.problem_alert_worker is not None:
            await self.problem_alert_worker.stop()
        await self.secret_expiry_worker.stop()
        await self.session_workspace_cleanup_worker.stop()
        if self.skill_upstream_worker is not None:
            await self.skill_upstream_worker.stop()


def build_platform_runtime(async_session_factory: object) -> PlatformRuntime:
    configure_persistent_process_runtime(async_session_factory)
    configure_durable_process_runtime(async_session_factory)
    return PlatformRuntime(
        async_session_factory=async_session_factory,
        task_scheduler=TaskScheduler(),
        retention_worker=RetentionWorker(async_session_factory),
        notification_delivery_worker=NotificationDeliveryWorker(async_session_factory),
        outbound_webhook_worker=OutboundWebhookWorker(async_session_factory),
        connector_health_worker=ConnectorHealthWorker(
            async_session_factory,
            run_connection_test=run_connector_connection_test,
        ),
        analytics_worker=AnalyticsWorker(async_session_factory),
        knowledge_projection_worker=KnowledgeProjectionWorker(async_session_factory),
        worker_monitor_worker=WorkerMonitorWorker(async_session_factory),
        worker_agenda_worker=WorkerAgendaWorker(async_session_factory),
        worker_report_worker=WorkerReportWorker(async_session_factory),
        worker_pool_worker=WorkerPoolAutoscaler(async_session_factory),
        sla_monitor_worker=SLAMonitorWorker(async_session_factory),
        problem_alert_worker=ProblemAlertWorker(async_session_factory),
        secret_expiry_worker=SecretExpiryWorker(async_session_factory),
        skill_upstream_worker=SkillUpstreamWorker(async_session_factory),
        session_workspace_cleanup_worker=SessionWorkspaceCleanupWorker(async_session_factory),
        runtime_ownership_worker=RuntimeOwnershipWorker(async_session_factory),
        knowledge_source_sync_scheduler=KnowledgeSourceSyncScheduler(async_session_factory),
        change_source_poll_worker=ChangeSourcePollWorker(async_session_factory),
        stale_approval_expiry_worker=StaleApprovalExpiryWorker(async_session_factory),
        knowledge_retention_reconcile_worker=KnowledgeRetentionReconcileWorker(async_session_factory),
        workflow_run_sweep_worker=WorkflowRunSweepWorker(async_session_factory),
        workflow_run_watch_worker=WatchPollWorker(async_session_factory),
        pull_request_refresh_worker=PullRequestRefreshWorker(async_session_factory),
        workflow_run_review_worker=ReviewWorker(async_session_factory),
        pr_review_sync_worker=PrReviewSyncWorker(async_session_factory),
        channel_reconciler=ChannelReconciler(async_session_factory),
        remote_stop_watcher=RemoteTurnStopWatcher(async_session_factory),
        mobile_push_sweeper=MobilePushSweeper(async_session_factory),
    )
