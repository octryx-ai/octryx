"""Account and user administration routes under ``/api/v1/auth``. Registered right after ``auth.py``'s router, so the
route order stays the same."""

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Personality, Role, User, UserRole
from ....schemas.core.auth import RegisterRequest, UserMeUpdate, UserResponse, UserUpdate
from ....services.auth import get_current_user, hash_password, verify_password
from ....web._helpers.api_guards import _enforce_same_origin_for_cookie_auth

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _require_same_origin_access_cookie(request: Request) -> None:
    _enforce_same_origin_for_cookie_auth(request, cookie_names=("access_token",))


async def role_names(db: AsyncSession, user_id: str) -> list[str]:
    result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return [row[0] for row in result.all()]


def user_response(user: User, roles: list[str]) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        roles=roles,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )


@router.post("/register", response_model=UserResponse)
async def register(
    body: RegisterRequest,
    _csrf_guard: None = Depends(_require_same_origin_access_cookie),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Only admin can register new users
    roles = set(await role_names(db, current_user.id))
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Only admins can register new users")

    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
    )
    db.add(user)
    await db.flush()

    viewer_role = await db.execute(select(Role).where(Role.name == "viewer"))
    role = viewer_role.scalar_one_or_none()
    if role:
        db.add(UserRole(user_id=user.id, role_id=role.id))

    db.add(Personality(user_id=user.id))

    await db.commit()

    return user_response(user, ["viewer"])


@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    roles = await role_names(db, current_user.id)
    return user_response(current_user, roles)


@router.put("/me", response_model=UserResponse)
async def update_user_me(
    body: UserMeUpdate,
    _csrf_guard: None = Depends(_require_same_origin_access_cookie),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.email is not None:
        result = await db.execute(select(User).where(User.email == body.email, User.id != current_user.id))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        current_user.email = body.email
    if body.display_name is not None:
        current_user.display_name = body.display_name
    await db.commit()
    await db.refresh(current_user)
    roles = await role_names(db, current_user.id)
    return user_response(current_user, roles)


@router.post("/me/password", response_model=dict)
async def change_password(
    body: dict = Body(...),
    _csrf_guard: None = Depends(_require_same_origin_access_cookie),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change password for the current user."""
    current_password = body.get("current_password")
    new_password = body.get("new_password")
    if not current_password or not new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current and new password required")
    if not verify_password(current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters"
        )
    current_user.password_hash = hash_password(new_password)
    # A credential change ends every device credential; the devices need a new `device enable`.
    from ....services.devices.credential import revoke_user_device_grants

    await revoke_user_device_grants(db, user_id=current_user.id)
    await db.commit()
    return {"message": "Password updated successfully"}


@router.get("", response_model=list[UserResponse])
async def list_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Only admin can list all users
    roles = set(await role_names(db, current_user.id))
    if "admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can list users")
    result = await db.execute(select(User))
    users = result.scalars().all()
    out = []
    for u in users:
        user_roles = await role_names(db, u.id)
        out.append(user_response(u, user_roles))
    return out


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Only admin can view other users
    roles = set(await role_names(db, current_user.id))
    if "admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can view other users")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user_roles = await role_names(db, user.id)
    return user_response(user, user_roles)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdate,
    _csrf_guard: None = Depends(_require_same_origin_access_cookie),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Only admin can update other users
    # Exact role-name match only, so a role like "not-admin" never counts as admin.
    roles = {name.strip().lower() for name in await role_names(db, current_user.id)}
    if "admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can update other users")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if body.username is not None:
        existing = await db.execute(select(User).where(User.username == body.username, User.id != user_id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")
        user.username = body.username
    if body.email is not None:
        existing = await db.execute(select(User).where(User.email == body.email, User.id != user_id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        if body.email != user.email and str(user_id) != str(current_user.id):
            # An admin's email change is account recovery: the person is told.
            from ....services.admin.governance.admin_user_service import _notify_account_recovery  # noqa: PLC0415

            await _notify_account_recovery(db, user.id, "Your email address was changed by an administrator")
        user.email = body.email
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.roles is not None:
        await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        for role_name in body.roles:
            if role_name.strip().lower() == "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="The 'admin' role cannot be assigned via this endpoint",
                )
            role_result = await db.execute(select(Role).where(Role.name == role_name))
            role = role_result.scalar_one_or_none()
            if role:
                db.add(UserRole(user_id=user_id, role_id=role.id))
    await db.commit()
    await db.refresh(user)
    user_roles = await role_names(db, user.id)
    return user_response(user, user_roles)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    _csrf_guard: None = Depends(_require_same_origin_access_cookie),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Only admin can delete (deactivate) users
    roles = set(await role_names(db, current_user.id))
    if "admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete users")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = False
    await db.commit()
    return None
