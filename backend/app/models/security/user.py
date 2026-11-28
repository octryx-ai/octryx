import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    auth_source = Column(String(30), nullable=False, default="local")
    account_type = Column(String(30), nullable=False, default="human")
    display_name = Column(String(200))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    roles = relationship("Role", secondary="user_roles", back_populates="users")
    identity_groups = relationship("IdentityGroup", secondary="user_groups", back_populates="users")
    projects = relationship(
        "Project",
        secondary="user_projects",
        primaryjoin="User.id == UserProject.user_id",
        secondaryjoin="Project.id == UserProject.project_id",
        back_populates="users",
    )
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    personality = relationship("Personality", back_populates="user", uselist=False)


class Role(Base):
    __tablename__ = "roles"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)

    users = relationship("User", secondary="user_roles", back_populates="roles")
    permissions = relationship("Permission", back_populates="role")


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    role_id = Column(String(36), ForeignKey("roles.id"), nullable=False)
    resource = Column(String(200), nullable=False)
    action = Column(String(50), nullable=False)

    role = relationship("Role", back_populates="permissions")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    role_id = Column(String(36), ForeignKey("roles.id"), primary_key=True)
    granted_at = Column(DateTime, default=utc_now)


class IdentityGroup(Base):
    __tablename__ = "identity_groups"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(120), unique=True, nullable=False, index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    rls_attributes_json = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now, index=True)

    users = relationship("User", secondary="user_groups", back_populates="identity_groups")


class UserGroup(Base):
    __tablename__ = "user_groups"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    group_id = Column(String(36), ForeignKey("identity_groups.id"), primary_key=True, index=True)
    granted_at = Column(DateTime, default=utc_now)


class ProjectGroup(WorkspaceBound, Base):
    __tablename__ = "project_groups"

    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True, index=True)
    group_id = Column(String(36), ForeignKey("identity_groups.id"), primary_key=True, index=True)
    role = Column(String(50), default="member")
    granted_by = Column(String(36), ForeignKey("users.id"))
    granted_at = Column(DateTime, default=utc_now)

    role_assignments = relationship(
        "ProjectGroupRoleAssignment",
        primaryjoin=(
            "and_(ProjectGroup.project_id == foreign(ProjectGroupRoleAssignment.project_id), "
            "ProjectGroup.group_id == foreign(ProjectGroupRoleAssignment.group_id))"
        ),
        viewonly=True,
    )


class UserProject(WorkspaceBound, Base):
    __tablename__ = "user_projects"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True)
    role = Column(String(50), default="member")
    granted_by = Column(String(36), ForeignKey("users.id"))
    granted_at = Column(DateTime, default=utc_now)

    role_assignments = relationship(
        "ProjectUserRoleAssignment",
        primaryjoin=(
            "and_(UserProject.user_id == foreign(ProjectUserRoleAssignment.user_id), "
            "UserProject.project_id == foreign(ProjectUserRoleAssignment.project_id))"
        ),
        viewonly=True,
    )


class ProjectUserRoleAssignment(WorkspaceBound, Base):
    """Normalized project-role assignments for a direct user/project grant. One row per (user, project, role_name): the
    only store of a direct grant's project roles."""

    __tablename__ = "project_user_role_assignments"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True, index=True)
    role_name = Column(String(50), primary_key=True)


class ProjectGroupRoleAssignment(WorkspaceBound, Base):
    """Normalized project-role assignments for a group/project grant. One row per (group, project, role_name): the only
    store of a group grant's project roles."""

    __tablename__ = "project_group_role_assignments"

    group_id = Column(String(36), ForeignKey("identity_groups.id"), primary_key=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True, index=True)
    role_name = Column(String(50), primary_key=True)
