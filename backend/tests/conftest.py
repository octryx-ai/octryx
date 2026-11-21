"""Test configuration and fixtures."""

import tests.network_guard  # noqa: F401, I001 - first: no test reaches the real network (tests/network_guard.py)
from tests.isolated_environment import (  # noqa: I001 - before any app import: databases, bcrypt cost
    APP_DATABASE_PATH,
    AUDIT_FALLBACK_PATH,
    TEST_DATABASE_PATH,
    TEST_DATABASE_URL,
    sqlite_files,
)

import asyncio
import atexit
import importlib
import os
import sqlite3
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import ResourceClosedError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main_module
import tests.scratch_sqlite_migrations  # noqa: F401 - alembic upgrades/downgrades skip fsync on scratch SQLite
from app.bootstrap import seed_database
from app.config import get_settings
from app.db import Base, get_db
from app.db import core as db_core
from app.db import init_db as db_init_db
from app.main import app
from app.middleware.security.rate_limit import clear_rate_limit_buckets
from app.models import (
    ControlPlaneConfig,
    ControlPlaneRuntimeTarget,
    LLMProvider,
    Project,
    User,
)
from app.services.auth_rate_limit import clear_all_auth_rate_limits
from app.services.chat_turn_background import cancel_chat_turn_background_tasks
from app.services.project_template_service import PROJECT_SOURCE_SAMPLE
from app.services.sample_workspace_bootstrap import ensure_sample_workspace_bootstrap
from app.services.session.turn_tasks import CHAT_RUN_TASKS
from tests.import_preload import preload as preload_workflow_run_modules
from tests.model_call_scope_plugin import (  # noqa: F401 - registers the driver-test scope and report evidence
    fresh_report_evidence,
    platform_model_call,
)
from tests.policy_engine_shadow_plugin import (  # noqa: F401 - registers the Cedar shadow-equality fixture
    policy_engine_shadow_equality,
    pytest_runtest_logreport,
    pytest_terminal_summary,
)

# The in-process HTTP harness (httpx ASGITransport) speaks plain HTTP from a
# loopback peer, i.e. exactly the explicit local-debug case of the auth-cookie
# policy. Pin that configuration here so shared cookie round-trips keep working
# even when the CI environment declares a production-like forced-secure policy;
# forced-secure/HTTPS/proxy behavior is proven by tests/test_auth_cookie_policy.py
# against explicit Settings instances instead of the shared harness.
os.environ["FORCE_SECURE_AUTH_COOKIES"] = "false"
os.environ["DEBUG"] = "true"
os.environ["TRUSTED_PROXY_IPS"] = ""
# The harness logs in as the seeded admin; production has no built-in password (first-start setup).
os.environ.setdefault("ADMIN_DEFAULT_PASSWORD", "admin")
# Audit rows the database refuses land in the temp directory, never in the checkout's backend/data.
importlib.import_module("app.middleware.audit.request_audit")._AUDIT_FALLBACK_FILE = AUDIT_FALLBACK_PATH
# App modules imported above may already have built the cached Settings from the
# ambient environment; rebuild it so the request-time cookie policy sees the
# harness configuration.
get_settings.cache_clear()

# Origin the in-process HTTP harness speaks from. It is both the client's
# ``base_url`` (and therefore the ``Host`` the app sees) and the ``Origin`` header
# the harness sends, so harness requests are same-origin by construction.
HARNESS_ORIGIN = "http://test"

# Admin password used by test fixtures — read from settings at import time
ADMIN_PASSWORD = get_settings().admin_default_password


def _ensure_office_sample_artifact() -> None:
    sample_path = Path(__file__).resolve().parents[2] / "data" / "office-samples" / "project-proposal.docx"
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    if not sample_path.exists():
        sample_path.write_text("Octryx office sample artifact.\n", encoding="utf-8")


def _ensure_chat_static_artifact() -> None:
    chat_static_dir = Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "chat"
    assets_dir = chat_static_dir / "assets"
    index_path = chat_static_dir / "index.html"
    assets_dir.mkdir(parents=True, exist_ok=True)
    if not index_path.exists():
        index_path.write_text(
            '<!doctype html><html><body><div id="root"></div><script type="module" '
            'src="/admin/static/chat/assets/test.js"></script></body></html>',
            encoding="utf-8",
        )


_ensure_office_sample_artifact()
_ensure_chat_static_artifact()

# Tests must not inherit the developer's .env knowledge-embedding config
# (e.g. in_process/bge on a dev machine): pin the deterministic hash provider.
# The process environment takes precedence over pydantic settings, and tests
# that exercise other providers set these explicitly via monkeypatch.
os.environ.setdefault("OCTRYX_KNOWLEDGE_EMBEDDING_PROVIDER", "local_hash")
os.environ.setdefault("OCTRYX_KNOWLEDGE_EMBEDDING_MODEL", "hash-embedding-v1")
# Tests must never inherit the dev instance federation key; endpoint tests
# that need one set it explicitly.
os.environ["OCTRYX_KNOWLEDGE_FEDERATION_SIGNING_KEY"] = ""

# Before any test can monkeypatch a workflow-run module: no lazy first import may capture a test's fake.
preload_workflow_run_modules()

# File-based SQLite per process (tests/isolated_environment.py).
# WAL journal mode + shared cache allow concurrent connections within the same process
_test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 120},
    # NullPool: every session.open() grabs a brand-new aiosqlite connection.
    # This sidesteps SQLite's single-writer lock contention entirely — WAL
    # allows concurrent connections to coexist safely for reads, and each
    # writer runs to completion on its own connection before closing.
    poolclass=NullPool,
)
_test_session_factory = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)



def _remove_test_database() -> None:
    """Drop this process's database files and their SQLite side files (one set per pytest process, never reused)."""
    _test_engine.sync_engine.dispose()
    for path in (*sqlite_files(TEST_DATABASE_PATH), *sqlite_files(APP_DATABASE_PATH), AUDIT_FALLBACK_PATH):
        path.unlink(missing_ok=True)


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001 - pytest hook signature
    _remove_test_database()


# A process that dies before sessionfinish (crash, Ctrl-C mid-collection) still removes its file.
atexit.register(_remove_test_database)

# Expose at module level for tests that need to inspect the engine directly
test_engine = _test_engine
shared_test_session_factory = _test_session_factory


async def _seed_fallback_runtime_target(db: AsyncSession) -> ControlPlaneRuntimeTarget:
    """Create a minimal runtime target + provider when seed_database skips it (no llm_provider configured)."""
    existing = (
        (await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.is_active.is_(True))))
        .scalars()
        .first()
    )
    if existing:
        return existing
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        provider_family="github",
        driver="copilot_api",
        runtime_kind="api",
        display_name="Copilot (Default)",
        auth_mode="auth_session",
        default_model_id="claude-sonnet-4-20250514",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()
    config_result = await db.execute(select(ControlPlaneConfig).where(ControlPlaneConfig.name == "default"))
    config = config_result.scalar_one_or_none()
    if not config:
        config = ControlPlaneConfig(
            id=str(uuid.uuid4()),
            name="default",
            model_id=provider.default_model_id,
            is_active=True,
        )
        db.add(config)
        await db.flush()
    target = ControlPlaneRuntimeTarget(
        id=str(uuid.uuid4()),
        config_id=config.id,
        provider_id=provider.id,
        model_id=provider.default_model_id,
        priority=1,
        is_active=True,
    )
    db.add(target)
    await db.flush()
    return target


# ---------------------------------------------------------------------------
# One-time schema initialisation at module import time
# ---------------------------------------------------------------------------
_test_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_test_loop)


async def _init_schema():
    """Run once: create all tables."""
    clear_all_auth_rate_limits()
    clear_rate_limit_buckets()
    CHAT_RUN_TASKS.clear()
    async with _test_engine.begin() as conn:
        # Set pragmas explicitly: WAL is required for concurrent readers, and a
        # long busy_timeout prevents "database is locked" from brief SQLite writer
        # contention between the test engine and prod engine connections.
        await conn.run_sync(
            lambda sync_conn: (
                sync_conn.execute(text("PRAGMA journal_mode=WAL")),
                sync_conn.execute(text("PRAGMA busy_timeout=120000")),
                sync_conn.execute(text("PRAGMA synchronous=NORMAL")),
                sync_conn.execute(text("PRAGMA foreign_keys=ON")),
            )
        )
        await conn.run_sync(Base.metadata.create_all)


_test_loop.run_until_complete(_init_schema())
_test_loop.close()


async def _clear_all_tables(db: AsyncSession) -> None:
    """Clear all rows so the pre-existing schema stays intact across test runs.

    The temp SQLite DB is created once per test process. Using DELETE (not DROP)
    preserves the schema that was set up when the first db fixture ran init_db.
    This prevents "index already exists" errors on re-runs and "no such column"
    errors when Base.metadata includes columns the existing tables don't have.
    """
    await db.execute(text("PRAGMA foreign_keys=OFF"))
    for table in reversed(Base.metadata.sorted_tables):
        await db.execute(table.delete())
    await db.execute(text("PRAGMA foreign_keys=ON"))


async def _switch_optional_workflows_on(db: AsyncSession) -> None:
    """The suite runs every shipped workflow, the optional ones too; ``test_shipped_workflows`` checks what a fresh
    installation really has active."""
    from app.models import FlowDefinition
    from app.services.workflow_runs.seeding import AVAILABILITY_OPTIONAL, phased_seeds

    optional = {seed["key"] for seed in phased_seeds() if seed.get("availability") == AVAILABILITY_OPTIONAL}
    for flow in (await db.execute(select(FlowDefinition).where(FlowDefinition.key.in_(optional),
                                                               FlowDefinition.project_id.is_(None)))).scalars():
        flow.is_active = True
    await db.flush()


async def _publish_engineering_base(db: AsyncSession) -> None:
    """B (``feature-delivery-tdd``), the base the accepted-spec engineering graph is derived from, published as an
    admin would: not a shipped workflow, but the richest test-first graph, which many engine tests run."""
    from app.models import FlowDefinition
    from app.services.flow_definitions import create_flow_definition, publish_flow_definition_version
    from app.services.workflow_runs.seeding import SEED_MARKER, definition_digest
    from tests.specification_engineering_graph_support import base_seed

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
    seed = base_seed()
    if admin is None or (await db.execute(select(FlowDefinition).where(
            FlowDefinition.key == seed["key"], FlowDefinition.project_id.is_(None)))).scalars().first():
        return
    created = await create_flow_definition(db, current_user=admin, payload={
        "key": seed["key"], "name": "Feature delivery (TDD)", "description": "The engineering graph's base.",
        "definition": seed["definition"],
        "runtime_settings": {"seed": SEED_MARKER, "seed_digest": definition_digest(seed["definition"])}})
    await publish_flow_definition_version(db, version_id=created["versions"][0]["id"], current_user=admin,
                                          shipped=True)
    await db.flush()


async def _seed_test_baseline(db: AsyncSession, *, include_legacy_projects: bool) -> None:
    await _clear_all_tables(db)
    await seed_database(db)
    await _switch_optional_workflows_on(db)
    await _publish_engineering_base(db)
    # The built-in agents the engine tests need, as a test fixture (never product boot).
    from app.services.agent_builtins import ensure_builtin_agents

    baseline_admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await ensure_builtin_agents(db, admin_user=baseline_admin)
    await _seed_fallback_runtime_target(db)
    # The product refuses an unpriced platform-billed model under a cost cap. Many engine
    # tests run fake, unpriced Bedrock models that have nothing to do with budgets, so the test baseline warns;
    # the cost-cap tests (test_observability_usage.py) set "block" themselves.
    from app.services.budget.unpriced_guard import POLICY_WARN, set_unpriced_model_policy

    await set_unpriced_model_policy(db, POLICY_WARN)

    if include_legacy_projects:
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
        if admin is not None:
            demo = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one_or_none()
            if not demo:
                demo = Project(
                    id=str(uuid.uuid4()),
                    name="demo",
                    description="Demo project with sample configuration",
                    config={
                        "grafana_url": "https://grafana.example.com",
                        "prometheus_url": "https://prometheus.example.com",
                        "loki_url": "https://loki.example.com",
                        "k8s_context": "demo-cluster",
                    },
                    is_active=True,
                    source_type=PROJECT_SOURCE_SAMPLE,
                )
                db.add(demo)
                await db.flush()
            await ensure_sample_workspace_bootstrap(db, admin_user=admin)
    await db.commit()


async def _seed_committed_baseline(*, include_legacy_projects: bool = True) -> None:
    """Build the committed baseline once for transaction-backed tests."""
    async with _test_session_factory() as session:
        await _seed_test_baseline(session, include_legacy_projects=include_legacy_projects)


async def _init_app_database() -> None:
    """The app's own default database (a per-process scratch file) gets the schema once, as it always had one."""
    await db_core.async_engine.dispose()
    await db_init_db()
    await db_core.async_engine.dispose()


# ---------------------------------------------------------------------------
# Committed baselines: seeded once per process, restored by copy
# ---------------------------------------------------------------------------
# A committed-DB test starts from a seeded database without reseeding it (seeding costs seconds: ~800 prompt keys,
# bootstrap, fixtures). The seeded state is kept as an in-memory SQLite copy per baseline (with and without the
# project templates) and copied back with the SQLite backup API.
_BASELINE_SNAPSHOTS: dict[bool, sqlite3.Connection] = {}


def _copy_database(source: sqlite3.Connection | Path, target: sqlite3.Connection | Path) -> None:
    """Copy every page of one SQLite database into another (the backup API retries while a reader holds a lock)."""
    src = source if isinstance(source, sqlite3.Connection) else sqlite3.connect(source)
    dst = target if isinstance(target, sqlite3.Connection) else sqlite3.connect(target, timeout=120)
    try:
        src.backup(dst)
    finally:
        if src is not source:
            src.close()
        if dst is not target:
            dst.close()


def _snapshot_baseline(include_legacy_projects: bool) -> None:
    _test_engine.sync_engine.dispose()
    snapshot = sqlite3.connect(":memory:", check_same_thread=False)
    _copy_database(TEST_DATABASE_PATH, snapshot)
    _BASELINE_SNAPSHOTS[include_legacy_projects] = snapshot


async def _settle_background_work() -> None:
    """Stop what a test left running on this loop (a triggered task's agent turn, a chat turn) before the database is
    replaced underneath it: a live connection would hold the SQLite lock, and the backup API retries a busy target
    forever (a full gate would hang)."""
    await cancel_chat_turn_background_tasks()
    current = asyncio.current_task()
    others = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
    for task in others:
        task.cancel()
    if others:
        await asyncio.wait(others, timeout=10)


def _assert_target_unlocked(target: Path, timeout_s: float = 30.0) -> None:
    """Fail loudly instead of hanging when something still holds the test database (the backup API never times out)."""
    probe = sqlite3.connect(target, timeout=timeout_s)
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.rollback()
    except sqlite3.OperationalError as exc:
        raise RuntimeError(f"test database still locked after {timeout_s:.0f}s by a connection the test left open") from exc
    finally:
        probe.close()


async def _restore_committed_baseline(*, include_legacy_projects: bool = True) -> None:
    """Bring the test database back to a seeded baseline; the first request for a baseline seeds and keeps it."""
    snapshot = _BASELINE_SNAPSHOTS.get(include_legacy_projects)
    if snapshot is None:
        await _seed_committed_baseline(include_legacy_projects=include_legacy_projects)
        _snapshot_baseline(include_legacy_projects)
        return
    await _settle_background_work()
    await _test_engine.dispose()
    _assert_target_unlocked(TEST_DATABASE_PATH)
    _copy_database(snapshot, TEST_DATABASE_PATH)


_test_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_test_loop)
_test_loop.run_until_complete(_seed_committed_baseline(include_legacy_projects=True))
_test_loop.run_until_complete(_init_app_database())
_test_loop.close()
_snapshot_baseline(include_legacy_projects=True)


@event.listens_for(_test_engine.sync_engine, "begin")
def _begin_test_transaction(conn):
    """Force a real SQLite transaction so SAVEPOINT rollback isolates commits."""
    try:
        force_begin = conn.info.get("force_test_transaction_begin")
    except ResourceClosedError:
        return
    if force_begin:
        conn.exec_driver_sql("BEGIN")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _workflow_proposals_off_unless_marked(request, monkeypatch):
    """Workflow proposals add one governed pre-turn model call to turns without a
    ``workflow_key``. The product default is on; in the suite they are off so suites that
    script provider calls are unaffected. Tests that pin proposal behaviour opt in with
    ``@pytest.mark.workflow_proposals``.
    """
    if request.node.get_closest_marker("workflow_proposals"):
        return
    from app.services.workflow_routing import proposal as workflow_proposal_module

    async def _proposals_off(_db, _project_id):
        return False

    monkeypatch.setattr(workflow_proposal_module, "workflow_proposals_enabled", _proposals_off)


@pytest.fixture(autouse=True)
def _repository_steps_inline_unless_marked(request, monkeypatch):
    """``scm.create_branch`` / ``scm.checkout`` run after the request in the product (``deferred_action``); the suite
    runs them inline so flow tests read the step's result at once. Tests of the deferral opt in with
    ``@pytest.mark.deferred_actions``."""
    if request.node.get_closest_marker("deferred_actions"):
        return
    from app.services.workflow_runs import deferred_action

    monkeypatch.setattr(deferred_action, "RUN_INLINE", True)


@pytest.fixture(autouse=True)
def _health_checks_stored_before_the_answer(monkeypatch):
    """The service stores health checks in a background task; in the suite that task would use the one shared
    test connection while the test does ("session in prepared state"). Tests store them before the answer;
    ``test_a_busy_connection_pool_never_holds_the_probe`` pins the background store.
    """
    from app.services.observability import health_checks

    monkeypatch.setattr(health_checks, "PERSIST_INLINE", True)


@pytest.fixture(autouse=True)
def _seed_policy_lists_per_test():
    """The live policy lists are a process snapshot; every test starts and ends on the seed."""
    from app.services.policy_lists.live import reset_live_policy_lists

    reset_live_policy_lists()
    yield
    reset_live_policy_lists()


@pytest.fixture(autouse=True)
def _jira_api_versions_unlearned():
    """Each test starts with no remembered Jira REST API version (process memory, ``_jira_api_versions``)."""
    from app.tools.jira_impl._jira_api_versions import forget_api_versions

    forget_api_versions()
    yield
    forget_api_versions()


@pytest.fixture(autouse=True)
def _bedrock_model_catalog_offline(monkeypatch):
    """The Bedrock client reads the model catalog before a bare model id; never in the suite.

    An empty catalog keeps the existing inference-profile behaviour; tests of the catalog rule
    patch ``_list_foundation_model_summaries`` themselves.
    """
    from app.agent.providers import bedrock_model_ids
    from app.agent.providers.bedrock import BedrockClient

    bedrock_model_ids.clear_catalog_cache()
    monkeypatch.setattr(BedrockClient, "_list_foundation_model_summaries", lambda self: [])
    yield
    bedrock_model_ids.clear_catalog_cache()



@pytest.fixture(autouse=True)
def _seed_prompt_set_for_code_outside_a_turn():
    """Bind the seed prompt set for code that unit tests call outside a turn.

    Production binds each turn's resolved set in run preparation and refuses to render
    unbound (``prompt_set_unbound``); ``tests/test_prompt_catalog_contract.py`` pins both,
    unbinding explicitly with ``prompt_set_scope(None)``.
    """
    from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set

    with prompt_set_scope(seed_prompt_set()):
        yield


@pytest_asyncio.fixture
async def db(request):
    """Per-test session isolated by an outer transaction and SAVEPOINT rollback."""
    clear_all_auth_rate_limits()
    clear_rate_limit_buckets()
    pending = [task for task in CHAT_RUN_TASKS.values() if not task.done()]
    CHAT_RUN_TASKS.clear()
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    await cancel_chat_turn_background_tasks()

    include_legacy_projects = request.node.get_closest_marker("without_legacy_project_templates") is None
    use_committed_db = request.node.get_closest_marker("committed_db") is not None
    if use_committed_db or not include_legacy_projects:
        await _restore_committed_baseline(include_legacy_projects=include_legacy_projects)
        async with _test_session_factory() as session:
            yield session
            await session.rollback()
        await _restore_committed_baseline(include_legacy_projects=True)
        return

    async with _test_engine.connect() as connection:
        connection.sync_connection.info["force_test_transaction_begin"] = True
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
            connection.sync_connection.info.pop("force_test_transaction_begin", None)


@pytest_asyncio.fixture
async def reset_db(request):
    """For tests that need the committed database restored to its seeded baseline."""
    include_legacy_projects = request.node.get_closest_marker("without_legacy_project_templates") is None
    await _restore_committed_baseline(include_legacy_projects=include_legacy_projects)
    async with _test_session_factory() as session:
        yield session
        await session.rollback()
    await _restore_committed_baseline(include_legacy_projects=True)


@pytest_asyncio.fixture
async def client(request, db: AsyncSession):
    """Per-test HTTP client. db dependency ensures rate-limit buckets are cleared."""

    class SharedSessionContext:
        async def __aenter__(self) -> AsyncSession:
            return db

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    def shared_session_factory() -> SharedSessionContext:
        return SharedSessionContext()

    use_committed_db = request.node.get_closest_marker("committed_db") is not None

    # Override get_db to use the same db session for transaction-backed tests.
    # Committed DB tests intentionally use independent sessions because they
    # exercise background work or other concurrent request activity.
    async def override_get_db():
        if use_committed_db:
            async with _test_session_factory() as session:
                yield session
            return
        yield db

    original_engine = db_core.async_engine
    db_core.async_engine = _test_engine
    original_is_sqlite = db_core._is_sqlite
    db_core._is_sqlite = True
    # Also patch async_session_factory so startup code using it hits test DB
    original_factory = db_core.async_session_factory
    session_factory = _test_session_factory if use_committed_db else shared_session_factory
    db_core.async_session_factory = session_factory
    try:
        app.dependency_overrides[get_db] = override_get_db
        app.state.async_session_factory = session_factory
        main_module.platform_runtime.async_session_factory = session_factory
        main_module.task_scheduler.set_session_factory(session_factory)
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url=HARNESS_ORIGIN,
            # Browsers send ``Origin`` on every state-changing request, and
            # the panel same-origin boundary refuses a cookie mutation that
            # claims no origin. httpx sends none on its own, so the harness has
            # to model the browser it stands in for; a test that needs the
            # missing/foreign-origin cases overrides this header explicitly.
            headers={"Origin": HARNESS_ORIGIN},
        ) as ac:
            yield ac
        app.dependency_overrides.clear()
    finally:
        db_core.async_engine = original_engine
        db_core._is_sqlite = original_is_sqlite
        db_core.async_session_factory = original_factory
    # Do NOT reset app.state.async_session_factory here — the app is
    # scoped to the test process, not per-test, and other tests that
    # run in the SAME session after this one may legitimately need it.


async def send_without_origin(client: AsyncClient, method: str, url: str, **kwargs):
    """Send one request with no ``Origin`` header at all.

    The shared client sends ``Origin`` like a browser. A test that needs
    the origin-less case — a non-browser client, or a browser that strips the
    header — has to take it back off for that one request, which is what this
    does; httpx offers no per-request header removal.
    """
    request = client.build_request(method, url, **kwargs)
    request.headers.pop("origin", None)
    return await client.send(request)


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict:
    """Login as admin and return auth headers."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth_user(db: AsyncSession) -> User:
    """Return the seeded admin User object from the current test db session."""
    result = await db.execute(select(User).where(User.username == "admin"))
    user = result.scalar_one_or_none()
    assert user is not None, "admin user not found in test db"
    return user
