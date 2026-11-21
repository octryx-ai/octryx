"""The Bitbucket policy project shared by the Bitbucket tool tests."""

import uuid

from app.models import CodeRepository, Project


async def _create_bitbucket_policy_project(
    db,
    *,
    repo_root: str,
    operation_policy: dict[str, bool] | None = None,
) -> str:
    project = Project(name=f"bitbucket-tools-{uuid.uuid4()}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    project_id = str(project.id)
    db.add(
        CodeRepository(
            project_id=project_id,
            name="acme-orders-catalog-plugin",
            provider="bitbucket",
            repo_root=repo_root,
            remote_url="https://scm.example.test/bitbucket/scm/SHOP/acme-orders-catalog-plugin.git",
            config_json={
                "operation_policy": operation_policy
                or {"read": True, "branch": True, "write": True, "pr": True}
            },
        )
    )
    await db.commit()
    return project_id
