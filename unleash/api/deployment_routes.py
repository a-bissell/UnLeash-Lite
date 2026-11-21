"""Deployment API routes — push a package to robots over OTA."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import CurrentUser, require_role
from ..audit.logger import log_action
from ..db.engine import get_session
from ..db.models import Deployment, DeploymentTarget, Package
from ..packages.schemas import DeploymentCreate, DeploymentDetailOut, DeploymentOut, DeploymentTargetOut

router = APIRouter(prefix="/deployments", tags=["deployments"])

_service = None


def set_service(service):
    global _service
    _service = service


async def _detail(session: AsyncSession, deployment_id: str) -> DeploymentDetailOut:
    deployment = (await session.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )).scalar_one()
    targets = (await session.execute(
        select(DeploymentTarget)
        .where(DeploymentTarget.deployment_id == deployment_id)
        .order_by(DeploymentTarget.robot_serial)
    )).scalars().all()
    return DeploymentDetailOut(
        id=deployment.id,
        package_id=deployment.package_id,
        strategy=deployment.strategy,
        target_type=deployment.target_type,
        target_value=deployment.target_value,
        status=deployment.status,
        created_at=deployment.created_at,
        completed_at=deployment.completed_at,
        targets=[DeploymentTargetOut.model_validate(t) for t in targets],
    )


@router.post("", response_model=DeploymentDetailOut, status_code=201)
async def create_deployment(
    body: DeploymentCreate,
    request: Request,
    user: CurrentUser = Depends(require_role("operator")),
    session: AsyncSession = Depends(get_session),
):
    if _service is None:
        raise HTTPException(status_code=503, detail="Deployment service not available")
    if body.target_type not in ("all", "group", "serial_list"):
        raise HTTPException(status_code=400, detail="target_type must be all, group, or serial_list")

    pkg = (await session.execute(
        select(Package).where(Package.id == body.package_id)
    )).scalar_one_or_none()
    if pkg is None or pkg.is_archived:
        raise HTTPException(status_code=404, detail="Package not found")

    deployment = await _service.create(
        session, pkg, body.target_type, body.target_value, body.strategy, user.user_id,
    )
    # Capture the id before any expire/refresh: touching an expired attribute
    # later would trigger implicit (non-awaited) IO and fail under asyncio.
    deployment_id = deployment.id

    target_count = (await session.execute(
        select(func.count(DeploymentTarget.id)).where(DeploymentTarget.deployment_id == deployment_id)
    )).scalar_one()
    if target_count == 0:
        # Created, but nothing resolved — surface it rather than silently no-op.
        raise HTTPException(status_code=400, detail="No robots matched the target selection")

    await _service.dispatch(deployment_id)

    await log_action(
        session, user.username, "create_deployment",
        user_id=user.user_id,
        target_type="deployment", target_id=deployment_id,
        detail={
            "package_id": body.package_id,
            "target_type": body.target_type,
            "target_value": body.target_value,
            "strategy": body.strategy,
        },
        ip_address=request.client.host if request.client else None,
    )

    # dispatch() mutated rows through a separate session; drop cached state
    # so we re-read the committed statuses.
    session.expire_all()
    return await _detail(session, deployment_id)


@router.get("", response_model=list[DeploymentOut])
async def list_deployments(
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Deployment).order_by(Deployment.created_at.desc()))
    return result.scalars().all()


@router.get("/{deployment_id}", response_model=DeploymentDetailOut)
async def get_deployment(
    deployment_id: str,
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    exists = (await session.execute(
        select(Deployment.id).where(Deployment.id == deployment_id)
    )).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return await _detail(session, deployment_id)
