import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.integration.channel_config import ChannelConfig
from ...models.json_text import safe_json_dict
from ...models.project.project import Project
from ...schemas.comms.channel_config import ChannelConfigResponse
from .service_user import deactivate_channel_service_user, ensure_channel_service_user


class ChannelConfigService:
    @staticmethod
    def _to_response(config: ChannelConfig, project_name: str | None = None) -> ChannelConfigResponse:
        return ChannelConfigResponse(
            id=config.id,
            plugin_id=config.plugin_id,
            name=config.name,
            project_id=config.project_id,
            project_name=project_name,
            enabled=config.enabled,
            config=safe_json_dict(config.config),
            updated_at=config.updated_at,
        )

    @staticmethod
    async def get_all(db: AsyncSession) -> list[ChannelConfigResponse]:
        result = await db.execute(select(ChannelConfig).order_by(ChannelConfig.plugin_id.asc(), ChannelConfig.id.asc()))
        configs = result.scalars().all()
        project_ids = {cfg.project_id for cfg in configs if cfg.project_id}
        project_names: dict[str, str] = {}
        if project_ids:
            rows = await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
            project_names = {project_id: name for project_id, name in rows.all()}
        return [ChannelConfigService._to_response(cfg, project_names.get(cfg.project_id or "")) for cfg in configs]

    @staticmethod
    async def get(db: AsyncSession, channel_id: int) -> ChannelConfigResponse | None:
        config = await db.get(ChannelConfig, channel_id)
        if config is None:
            return None
        project_name = None
        if config.project_id:
            project = await db.get(Project, config.project_id)
            project_name = project.name if project else None
        return ChannelConfigService._to_response(config, project_name)

    @staticmethod
    async def get_model(db: AsyncSession, channel_id: int) -> ChannelConfig | None:
        return await db.get(ChannelConfig, channel_id)

    @staticmethod
    async def get_enabled_by_plugin_id(db: AsyncSession, plugin_id: str) -> list[ChannelConfigResponse]:
        result = await db.execute(
            select(ChannelConfig)
            .where(ChannelConfig.plugin_id == plugin_id, ChannelConfig.enabled)
            .order_by(ChannelConfig.id.asc())
        )
        configs = result.scalars().all()
        project_ids = {cfg.project_id for cfg in configs if cfg.project_id}
        project_names: dict[str, str] = {}
        if project_ids:
            rows = await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))
            project_names = {project_id: name for project_id, name in rows.all()}
        return [ChannelConfigService._to_response(cfg, project_names.get(cfg.project_id or "")) for cfg in configs]

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        plugin_id: str,
        name: str,
        project_id: str | None,
        enabled: bool,
        config: dict,
    ) -> ChannelConfigResponse:
        new_config = ChannelConfig(
            plugin_id=plugin_id,
            name=name.strip() or plugin_id,
            project_id=project_id or None,
            enabled=enabled,
            config=json.dumps(config),
        )
        db.add(new_config)
        await db.flush()
        # Channel setup provisions the channel's own low-privilege service user.
        await ensure_channel_service_user(db, new_config)
        await db.commit()
        await db.refresh(new_config)
        project_name = None
        if new_config.project_id:
            project = await db.get(Project, new_config.project_id)
            project_name = project.name if project else None
        return ChannelConfigService._to_response(new_config, project_name)

    @staticmethod
    async def update(
        db: AsyncSession,
        channel_id: int,
        *,
        name: str | None = None,
        project_id: str | None = None,
        enabled: bool | None = None,
        config: dict | None = None,
    ) -> ChannelConfigResponse | None:
        existing = await db.get(ChannelConfig, channel_id)
        if existing is None:
            return None
        if name is not None:
            existing.name = name.strip() or existing.plugin_id
        if project_id is not None:
            existing.project_id = project_id or None
        if enabled is not None:
            existing.enabled = enabled
        if config is not None:
            existing.config = json.dumps(config)
        await ensure_channel_service_user(db, existing)
        await db.commit()
        await db.refresh(existing)
        project_name = None
        if existing.project_id:
            project = await db.get(Project, existing.project_id)
            project_name = project.name if project else None
        return ChannelConfigService._to_response(existing, project_name)

    @staticmethod
    async def delete(db: AsyncSession, channel_id: int) -> bool:
        config = await db.get(ChannelConfig, channel_id)
        if config is None:
            return False
        await deactivate_channel_service_user(db, config.id)
        await db.delete(config)
        await db.commit()
        return True
