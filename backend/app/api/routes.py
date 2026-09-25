from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.errors import NotFoundError, TraceQError
from backend.app.domain.routes import StepInput, validate_steps
from backend.app.persistence.database import get_db
from backend.app.persistence.models import Item, RouteDefinition, RouteRevision, RouteStep
from backend.app.security.auth import Principal, require_critical_permission, require_permission
from backend.app.security.audit import write_audit
from backend.app.security.crypto import utcnow


router = APIRouter(prefix="/api/v1/routes", tags=["routes"])


class RouteCreate(BaseModel):
    code: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=255)
    steps: list[StepInput] = Field(min_length=1)


class RevisionCreate(BaseModel):
    steps: list[StepInput] = Field(min_length=1)


class RouteImport(RouteCreate):
    activate: bool = False


def _serialize(db: Session, route: RouteDefinition) -> dict:
    revisions = db.scalars(
        select(RouteRevision)
        .where(RouteRevision.route_id == route.id)
        .order_by(RouteRevision.revision)
    ).all()
    return {
        "id": route.id,
        "code": route.code,
        "name": route.name,
        "active_revision_id": route.active_revision_id,
        "revisions": [
            {
                "id": revision.id,
                "revision": revision.revision,
                "status": revision.status,
                "immutable_after": revision.immutable_after,
                "steps": [
                    {
                        "id": step.id,
                        "position": step.position,
                        "operation_id": step.operation_id,
                        "operation_name": step.operation_name,
                        "station_id": step.station_id,
                        "control_point_id": step.control_point_id,
                        "required": step.required_inspection,
                        "inspection_scope": step.inspection_scope,
                        "trust_policy_id": step.trust_policy_id,
                    }
                    for step in db.scalars(
                        select(RouteStep)
                        .where(RouteStep.route_revision_id == revision.id)
                        .order_by(RouteStep.position)
                    ).all()
                ],
            }
            for revision in revisions
        ],
    }


def _create_revision(
    db: Session,
    route: RouteDefinition,
    steps: list[StepInput],
    principal: Principal,
) -> RouteRevision:
    validate_steps(steps)
    current = db.scalar(
        select(func.max(RouteRevision.revision)).where(RouteRevision.route_id == route.id)
    ) or 0
    revision = RouteRevision(
        route_id=route.id, revision=current + 1, status="draft", created_by=principal.user_id
    )
    db.add(revision)
    db.flush()
    for position, step in enumerate(steps, start=1):
        db.add(
            RouteStep(
                route_revision_id=revision.id,
                position=position,
                operation_id=step.operation_id,
                operation_name=step.operation_name,
                station_id=step.station_id,
                control_point_id=step.control_point_id,
                required_inspection=step.required,
                inspection_scope=step.inspection_scope,
                trust_policy_id=step.trust_policy_id,
            )
        )
    return revision


@router.get("")
def list_routes(
    _: Principal = Depends(require_permission("VIEW_PRODUCT")),
    db: Session = Depends(get_db),
):
    return [_serialize(db, route) for route in db.scalars(select(RouteDefinition).order_by(RouteDefinition.code)).all()]


@router.post("")
def create_route(
    body: RouteCreate,
    principal: Principal = Depends(require_permission("MANAGE_ROUTES")),
    db: Session = Depends(get_db),
):
    if db.scalar(select(RouteDefinition).where(RouteDefinition.code == body.code)):
        raise TraceQError("ROUTE_CODE_EXISTS", "Route code already exists", 409)
    route = RouteDefinition(code=body.code, name=body.name)
    db.add(route)
    db.flush()
    revision = _create_revision(db, route, body.steps, principal)
    db.commit()
    return {"id": route.id, "revision_id": revision.id}


@router.get("/{route_id}")
def get_route(
    route_id: uuid.UUID,
    _: Principal = Depends(require_permission("VIEW_PRODUCT")),
    db: Session = Depends(get_db),
):
    route = db.get(RouteDefinition, route_id)
    if not route:
        raise NotFoundError("Route")
    return _serialize(db, route)


@router.post("/{route_id}/revisions")
def create_revision(
    route_id: uuid.UUID,
    body: RevisionCreate,
    principal: Principal = Depends(require_permission("MANAGE_ROUTES")),
    db: Session = Depends(get_db),
):
    route = db.get(RouteDefinition, route_id)
    if not route:
        raise NotFoundError("Route")
    revision = _create_revision(db, route, body.steps, principal)
    db.commit()
    return {"revision_id": revision.id, "revision": revision.revision}


@router.post("/{route_id}/activate")
def activate_revision(
    route_id: uuid.UUID,
    revision_id: uuid.UUID,
    reason: str,
    request: Request,
    principal: Principal = Depends(require_critical_permission("MANAGE_ROUTES")),
    db: Session = Depends(get_db),
):
    route = db.get(RouteDefinition, route_id)
    revision = db.get(RouteRevision, revision_id)
    if not route or not revision or revision.route_id != route.id:
        raise NotFoundError("Route revision")
    if route.active_revision_id and route.active_revision_id != revision.id:
        old = db.get(RouteRevision, route.active_revision_id)
        if old:
            old.status = "superseded"
    revision.status = "active"
    revision.immutable_after = revision.immutable_after or utcnow()
    route.active_revision_id = revision.id
    write_audit(db, action="route_revision_activation", outcome="success",
                actor_user_id=principal.user_id, session_id=principal.session_id,
                target_type="route_revision", target_id=str(revision.id), request_id=request.state.request_id,
                safe_details={"route_id": str(route.id), "revision": revision.revision, "reason": reason[:1000]})
    db.commit()
    return {"status": "active", "revision_id": revision.id}


@router.post("/import")
def import_route(
    body: RouteImport,
    request: Request,
    principal: Principal = Depends(require_critical_permission("MANAGE_ROUTES")),
    db: Session = Depends(get_db),
):
    route = db.scalar(select(RouteDefinition).where(RouteDefinition.code == body.code))
    if route is None:
        route = RouteDefinition(code=body.code, name=body.name)
        db.add(route)
        db.flush()
    revision = _create_revision(db, route, body.steps, principal)
    if body.activate:
        if route.active_revision_id and route.active_revision_id != revision.id:
            old_revision = db.get(RouteRevision, route.active_revision_id)
            if old_revision:
                old_revision.status = "superseded"
        revision.status = "active"
        revision.immutable_after = utcnow()
        route.active_revision_id = revision.id
    write_audit(db, action="route_import", outcome="success", actor_user_id=principal.user_id,
                session_id=principal.session_id, target_type="route", target_id=str(route.id),
                request_id=request.state.request_id,
                safe_details={"code": body.code, "revision": revision.revision, "activated": body.activate})
    db.commit()
    return {"route_id": route.id, "revision_id": revision.id}


@router.get("/{route_id}/export")
def export_route(
    route_id: uuid.UUID,
    _: Principal = Depends(require_permission("MANAGE_ROUTES")),
    db: Session = Depends(get_db),
):
    route = db.get(RouteDefinition, route_id)
    if not route:
        raise NotFoundError("Route")
    return _serialize(db, route)
