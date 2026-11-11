"""Data dictionary endpoints (C3-13, docs §3.2, §4.7).

``POST /data-dictionary`` generates the dictionary from the live schema (all four Postgres
schemas + the C3-owned Mongo shapes) and publishes an immutable version, or publishes a
supplied document. ``GET /data-dictionary`` returns the latest (or a named ``version``)
grouped by owner component; ``?format=csv`` returns a flat CSV. cloud_staff only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from homeai_common.auth import Principal, require_roles
from homeai_common.errors import ApiError
from homeai_common.pagination import Envelope, data_response
from sqlalchemy.orm import Session

from app.api.deps import get_reader_connection, get_session
from app.repositories.dictionary_repo import DictionaryRepo, VersionExists
from app.schemas.dictionary import GenerateRequest
from app.services import dictionary_service

router = APIRouter(prefix="/api/v1/data-dictionary", tags=["data-dictionary"])

cloud = require_roles("cloud_staff")


@router.post("", response_model=Envelope[dict], status_code=201, dependencies=[Depends(cloud)])
def publish(
    body: GenerateRequest,
    principal: Principal = Depends(require_roles("cloud_staff")),
    session: Session = Depends(get_session),
    reader_conn=Depends(get_reader_connection),
) -> dict:
    """Generate (from the live schema) or publish a dictionary version. 409 if it exists.

    Reflection reads schema c3 on C3's own (c3_app) session connection and c1/c2/c4 on the
    read-only (c3_reader) connection — no single role can USE all four schemas. A missing reader
    URL fails closed with a clear 503. The version row is always written on the c3_app session.
    """
    if body.generate:
        if reader_conn is None:
            raise ApiError(503, "dependency_unavailable", "reader database not configured")
        document = dictionary_service.generate(session.connection(), reader_conn, body.version)
    else:
        document = body.document

    repo = DictionaryRepo(session)
    try:
        repo.publish(body.version, document, principal.sub)
    except VersionExists as exc:
        raise ApiError(
            409, "version_exists", f"dictionary version {body.version} already exists"
        ) from exc
    session.commit()
    return data_response({"version": body.version, "entities": len(document.get("entities", []))})


@router.get("/versions", response_model=Envelope[list[dict]], dependencies=[Depends(cloud)])
def list_versions(session: Session = Depends(get_session)) -> dict:
    rows = DictionaryRepo(session).list_versions()
    return data_response(
        [
            {"version": r.version, "published_by": r.published_by, "published_at": r.published_at}
            for r in rows
        ]
    )


@router.get("", dependencies=[Depends(cloud)])
def get_dictionary(
    request: Request,
    version: str | None = Query(None, description="A specific version; defaults to the latest"),
    format: str | None = Query(None, pattern="^(csv)$", description="'csv' for a flat export"),
    session: Session = Depends(get_session),
):
    """Return the latest (or a named) dictionary grouped by component, or CSV with ?format=csv."""
    repo = DictionaryRepo(session)
    row = repo.get(version) if version else repo.latest()
    if row is None:
        raise ApiError(404, "not_found", "no dictionary version found")

    if format == "csv":
        csv_text = dictionary_service.to_csv(row.document)
        filename = f"data-dictionary-{row.version}.csv"
        return Response(
            content=csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return data_response(dictionary_service.group_by_component(row.document))
