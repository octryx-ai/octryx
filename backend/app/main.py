"""FastAPI application entrypoint."""

import logging
from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from .api.routes.platform.runtime_endpoints import router as runtime_endpoints_router
from .config import get_settings
from .db import async_session_factory
from .http_setup import configure_http
from .runtime_lifecycle import get_platform_runtime, get_task_scheduler, set_runtime_session_factory
from .runtime_setup import STATIC_DIR
from .runtime_toggles import (
    API_WORKERS_ENV,
    DISABLE_BACKGROUND_WORKERS_ENV,
    api_worker_count,
    background_workers_enabled,
)
from .services.knowledge.embedding.warmup import start_embedder_warmup
from .services.observability.logging import configure_json_logging
from .services.observability.metrics_listener import METRICS_PORT_ENV, metrics_port, start_metrics_listener
from .trusted_proxy_policy import uvicorn_forwarded_header_options

configure_json_logging()
settings = get_settings()
platform_runtime = get_platform_runtime(async_session_factory)
task_scheduler = get_task_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        knowledge_mcp_protocol_app = getattr(app.state, "knowledge_mcp_protocol_app", None)
        if knowledge_mcp_protocol_app is not None:
            await stack.enter_async_context(
                knowledge_mcp_protocol_app.router.lifespan_context(knowledge_mcp_protocol_app)
            )
        await platform_runtime.startup()
        start_embedder_warmup()
        await _start_internal_metrics(stack)
        yield
        await platform_runtime.shutdown()


async def _start_internal_metrics(stack: AsyncExitStack) -> None:
    if metrics_port() is None:
        return
    if api_worker_count() != 1:
        logging.getLogger(__name__).warning(
            "metrics_listener_skipped", extra={"reason": "several api processes", "env": METRICS_PORT_ENV})
        return
    listener = await start_metrics_listener(platform_runtime.metrics_payload, role="api")
    if listener is not None:
        stack.push_async_callback(listener.stop)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)
app.state.async_session_factory = async_session_factory
app.state.task_scheduler = task_scheduler
set_runtime_session_factory(app.state.async_session_factory)
configure_http(app, static_dir=STATIC_DIR)
app.include_router(runtime_endpoints_router)


@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/chat", status_code=307)


def uvicorn_process_options() -> dict[str, object]:
    workers = api_worker_count()
    if workers == 1:
        return {"reload": settings.debug}
    if background_workers_enabled():
        raise SystemExit(
            f"{API_WORKERS_ENV}={workers} requires {DISABLE_BACKGROUND_WORKERS_ENV}=1 and the background workers "
            "in their own process (python -m app.worker_main); otherwise every API process runs them."
        )
    return {"reload": False, "workers": workers}


def main():
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        **uvicorn_process_options(),
        # Forwarded headers are evaluated by the application's validated
        # trusted-proxy boundary, never trusted at the transport layer.
        **uvicorn_forwarded_header_options(),
    )


if __name__ == "__main__":
    main()
