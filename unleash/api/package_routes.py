"""Package management API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import CurrentUser, require_role
from ..audit.logger import log_action
from ..config import settings
from ..db.engine import get_session
from ..db.models import Package
from ..packages.builder import build_package_to_file
from ..packages.examples import EXAMPLE_PACKAGES
from ..packages.schemas import PackageCreate, PackageOut, PackageTemplateOut

router = APIRouter(prefix="/packages", tags=["packages"])


@router.get("", response_model=list[PackageOut])
async def list_packages(
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Package).where(Package.is_archived == False).order_by(Package.created_at.desc())
    )
    return result.scalars().all()


@router.get("/templates", response_model=list[PackageTemplateOut])
async def list_templates(
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Built-in example packages, used as starting points in the builder.

    Declared before /{package_id} so the literal path isn't captured as an id.
    """
    return [PackageTemplateOut(**t) for t in EXAMPLE_PACKAGES]


@router.get("/{package_id}", response_model=PackageOut)
async def get_package(
    package_id: str,
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    return pkg


@router.post("", response_model=PackageOut, status_code=201)
async def create_package(
    body: PackageCreate,
    request: Request,
    user: CurrentUser = Depends(require_role("operator")),
    session: AsyncSession = Depends(get_session),
):
    settings.package_dir.mkdir(parents=True, exist_ok=True)

    commands = [cmd.model_dump() for cmd in body.commands]
    filename = f"{body.name}_{body.version}.upk"
    output_path = settings.package_dir / filename

    path, md5, size = build_package_to_file(
        commands=commands,
        output=output_path,
        module_name=body.module_name,
        version=body.version,
    )

    pkg = Package(
        name=body.name,
        version=body.version,
        description=body.description,
        module_name=body.module_name,
        commands_json=json.dumps(commands),
        file_hash=md5,
        file_size=size,
        file_path=str(path),
        created_by=user.user_id,
    )
    session.add(pkg)
    await session.commit()
    await session.refresh(pkg)

    await log_action(
        session, user.username, "create_package",
        user_id=user.user_id,
        target_type="package", target_id=pkg.id,
        detail={"name": body.name, "version": body.version, "commands": len(commands)},
        ip_address=request.client.host if request.client else None,
    )
    return pkg


@router.get("/{package_id}/download")
async def download_package(
    package_id: str,
    _: CurrentUser = Depends(require_role("operator")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    return FileResponse(pkg.file_path, filename=f"{pkg.name}_{pkg.version}.upk")


@router.delete("/{package_id}")
async def archive_package(
    package_id: str,
    request: Request,
    user: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Package).where(Package.id == package_id))
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise HTTPException(status_code=404, detail="Package not found")
    pkg.is_archived = True
    await session.commit()

    await log_action(
        session, user.username, "archive_package",
        user_id=user.user_id,
        target_type="package", target_id=package_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"status": "archived"}
