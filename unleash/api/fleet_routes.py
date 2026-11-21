"""Fleet management API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth.dependencies import CurrentUser, require_role
from ..db.engine import get_session
from ..db.models import Robot, RobotGroup
from ..fleet.schemas import (
    FleetStatus, RobotGroupCreate, RobotGroupOut, RobotOut, RobotUpdate,
)

router = APIRouter(prefix="/fleet", tags=["fleet"])


@router.get("/status", response_model=FleetStatus)
async def fleet_status(
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Robot.status, func.count(Robot.id)).group_by(Robot.status)
    )
    counts = dict(result.all())
    return FleetStatus(
        total=sum(counts.values()),
        online=counts.get("online", 0),
        offline=counts.get("offline", 0),
        updating=counts.get("updating", 0),
        error=counts.get("error", 0),
    )


@router.get("/robots", response_model=list[RobotOut])
async def list_robots(
    status: str | None = None,
    group_id: str | None = None,
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    query = select(Robot).options(selectinload(Robot.group))
    if status:
        query = query.where(Robot.status == status)
    if group_id:
        query = query.where(Robot.group_id == group_id)
    query = query.order_by(Robot.serial)

    result = await session.execute(query)
    robots = result.scalars().all()
    return [
        RobotOut(
            id=r.id,
            serial=r.serial,
            model=r.model,
            nickname=r.nickname,
            firmware_version=r.firmware_version,
            ip_address=r.ip_address,
            status=r.status,
            last_seen=r.last_seen,
            first_seen=r.first_seen,
            group_id=r.group_id,
            group_name=r.group.name if r.group else None,
        )
        for r in robots
    ]


@router.get("/robots/{serial}", response_model=RobotOut)
async def get_robot(
    serial: str,
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Robot).options(selectinload(Robot.group)).where(Robot.serial == serial)
    )
    robot = result.scalar_one_or_none()
    if not robot:
        raise HTTPException(status_code=404, detail="Robot not found")
    return RobotOut(
        id=robot.id,
        serial=robot.serial,
        model=robot.model,
        nickname=robot.nickname,
        firmware_version=robot.firmware_version,
        ip_address=robot.ip_address,
        status=robot.status,
        last_seen=robot.last_seen,
        first_seen=robot.first_seen,
        group_id=robot.group_id,
        group_name=robot.group.name if robot.group else None,
    )


@router.put("/robots/{serial}", response_model=RobotOut)
async def update_robot(
    serial: str,
    body: RobotUpdate,
    _: CurrentUser = Depends(require_role("operator")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Robot).options(selectinload(Robot.group)).where(Robot.serial == serial)
    )
    robot = result.scalar_one_or_none()
    if not robot:
        raise HTTPException(status_code=404, detail="Robot not found")

    if body.nickname is not None:
        robot.nickname = body.nickname
    if body.model is not None:
        robot.model = body.model
    if body.group_id is not None:
        robot.group_id = body.group_id if body.group_id else None

    await session.commit()
    await session.refresh(robot)
    return RobotOut(
        id=robot.id,
        serial=robot.serial,
        model=robot.model,
        nickname=robot.nickname,
        firmware_version=robot.firmware_version,
        ip_address=robot.ip_address,
        status=robot.status,
        last_seen=robot.last_seen,
        first_seen=robot.first_seen,
        group_id=robot.group_id,
        group_name=robot.group.name if robot.group else None,
    )


@router.get("/groups", response_model=list[RobotGroupOut])
async def list_groups(
    _: CurrentUser = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(
            RobotGroup,
            func.count(Robot.id).label("robot_count"),
        )
        .outerjoin(Robot, Robot.group_id == RobotGroup.id)
        .group_by(RobotGroup.id)
        .order_by(RobotGroup.name)
    )
    return [
        RobotGroupOut(
            id=g.id,
            name=g.name,
            description=g.description,
            created_at=g.created_at,
            robot_count=count,
        )
        for g, count in result.all()
    ]


@router.post("/groups", response_model=RobotGroupOut, status_code=201)
async def create_group(
    body: RobotGroupCreate,
    user: CurrentUser = Depends(require_role("operator")),
    session: AsyncSession = Depends(get_session),
):
    group = RobotGroup(name=body.name, description=body.description, created_by=user.user_id)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return RobotGroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        robot_count=0,
    )
