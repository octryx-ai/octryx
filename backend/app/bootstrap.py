import logging
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import (
    Permission,
    Personality,
    Project,
    Role,
    User,
    UserProject,
    UserRole,
)
from .services.auth.first_admin import AUTH_SOURCE_SETUP_PENDING, log_setup_code, seed_credential
from .services.control_plane_service import ensure_control_plane_defaults
from .services.exec_policy import ensure_default_exec_policy_config
from .services.project_template_service import PROJECT_SOURCE_SAMPLE, ensure_default_project
from .services.prompt_catalog.seeding import ensure_prompt_catalog_seed
from .services.research_policy import ensure_default_research_policy_profiles
from .services.skill_catalog.categories import ensure_starter_categories
from .services.tool_config import upsert_tool_config

logger = logging.getLogger(__name__)

# The demo Workspace's sample connections (targets only, no credential): Workspace tool entries.
DEMO_TOOL_TARGETS = {
    "grafana": "https://grafana.example.com",
    "prometheus": "https://prometheus.example.com",
    "loki": "https://loki.example.com",
}

settings = get_settings()


async def _ensure_bootstrap_admin_safe(db: AsyncSession, *, admin_user: User, admin_role: Role) -> None:
    changed = False
    if not admin_user.is_active:
        admin_user.is_active = True
        changed = True
    if (admin_user.account_type or "human") != "human":
        admin_user.account_type = "human"
        changed = True

    assigned_roles = (
        await db.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == admin_user.id)
        )
    ).scalars().all()
    assigned_roles = sorted(assigned_roles)
    if assigned_roles != ["admin"]:
        await db.execute(sa_delete(UserRole).where(UserRole.user_id == admin_user.id))
        db.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))
        changed = True

    if changed:
        await db.flush()


async def seed_database(db: AsyncSession):
    await ensure_default_exec_policy_config(db)
    await ensure_default_research_policy_profiles(db)

    # 1. Create default roles
    role_map = {}
    for role_name in ["admin", "operator", "technical", "viewer"]:
        result = await db.execute(select(Role).where(Role.name == role_name))
        role = result.scalar_one_or_none()
        if not role:
            role = Role(name=role_name, description=f"Default {role_name} role")
            db.add(role)
            await db.flush()
        role_map[role_name] = role

    core_permissions = {
        "operator": {
            ("api_keys", "self_read"),
            ("api_keys", "self_write"),
            ("auth", "login"),
        },
        "viewer": {
            ("api_keys", "self_read"),
            ("api_keys", "self_write"),
            ("auth", "login"),
        },
        "technical": {
            ("api_keys", "self_read"),
        },
    }
    for role_name, permissions in core_permissions.items():
        existing_permissions = await db.execute(select(Permission).where(Permission.role_id == role_map[role_name].id))
        existing_keys = {
            (permission.resource, permission.action)
            for permission in existing_permissions.scalars().all()
        }
        for resource, action in permissions - existing_keys:
            db.add(Permission(role_id=role_map[role_name].id, resource=resource, action=action))

    # 2. Create default admin user
    result = await db.execute(select(User).where(User.username == "admin"))
    admin_user = result.scalar_one_or_none()

    if not admin_user:
        # No built-in password: without ADMIN_DEFAULT_PASSWORD the account waits for the first-start setup.
        credential = seed_credential()
        admin_user = User(
            id=str(uuid.uuid4()),
            username="admin",
            email=settings.admin_email,
            password_hash=credential.password_hash,
            auth_source=credential.auth_source,
            display_name="System Administrator",
            is_active=True,
        )
        db.add(admin_user)
        await db.flush()

        # Assign admin role
        db.add(UserRole(user_id=admin_user.id, role_id=role_map["admin"].id))

        # Create default personality for admin
        db.add(
            Personality(
                id=str(uuid.uuid4()),
                user_id=admin_user.id,
                language="en",
                detail_level="detailed",
                communication_style="technical",
                output_format="full",
            )
        )

    await _ensure_bootstrap_admin_safe(db, admin_user=admin_user, admin_role=role_map["admin"])
    if admin_user.auth_source == AUTH_SOURCE_SETUP_PENDING:
        log_setup_code(admin_user)
    # Only the platform agents and the phased workflows are seeded; the platform agents first, because the
    # phases of the workflows name them.
    from .services.platform_agents.seeding import seed_platform_agents

    await seed_platform_agents(db, admin_user=admin_user)
    # The generic phased workflows, seeded once.
    from .services.workflow_runs.seeding import seed_phased_workflows

    await seed_phased_workflows(db, admin_user=admin_user)
    await ensure_prompt_catalog_seed(db, admin_user=admin_user)

    await ensure_default_project(db, admin_user=admin_user)

    await db.flush()
    await ensure_starter_categories(db)

    if settings.seed_demo_project:
        # 5. Create default demo project
        result = await db.execute(select(Project).where(Project.name == "demo"))
        demo_project = result.scalar_one_or_none()

        if not demo_project:
            demo_project = Project(
                id=str(uuid.uuid4()),
                name="demo",
                description="Demo project with sample configuration",
                # Connection targets live in Workspace tool entries, never in Project.config.
                config={"k8s_context": "demo-cluster"},
                is_active=True,
                source_type=PROJECT_SOURCE_SAMPLE,
            )
            db.add(demo_project)
            await db.flush()

            # Assign admin to demo project
            db.add(UserProject(user_id=admin_user.id, project_id=demo_project.id, role="owner"))
            for tool_name, url in DEMO_TOOL_TARGETS.items():
                await upsert_tool_config(
                    db, tool_name=tool_name, project_id=demo_project.id, config={f"{tool_name}_url": url},
                    description="Demo project sample connection", is_active=True,
                )

    await ensure_control_plane_defaults(db)
    await db.commit()
    logger.info("[seed] Database seeded. Admin user: admin")
