from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.application.ingestion_service import (
    BatchTooLargeError,
    EmptyUploadError,
    UnsupportedFileTypeError,
    ingest_batch,
)
from app.application.rejection_store import (
    RejectionContext,
    RejectionStore,
    RejectionStoreUnavailableError,
    record_rejections_best_effort,
)
from app.infrastructure.db.models import User
from app.infrastructure.db.repositories.batch_repository import BatchRepository
from app.infrastructure.db.session import get_db
from app.infrastructure.mongo.client import get_rejection_store
from app.schemas.batches import BatchResponse, BatchSummary, RejectedRowDetailPage

router = APIRouter(prefix="/batches", tags=["batches"])

_ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/json",
    "application/vnd.ms-excel",  # some browsers send this for .csv
    "application/octet-stream",  # generic fallback some clients send
}


@router.post("/upload", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
async def upload_batch(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    rejection_store: RejectionStore = Depends(get_rejection_store),
) -> BatchResponse:
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file has no filename.")

    if file.content_type and file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported content type '{file.content_type}'. Upload a .csv or .json file.",
        )

    raw_bytes = await file.read()

    try:
        result = ingest_batch(
            db=db,
            uploaded_by_user_id=current_user.id,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            raw_bytes=raw_bytes,
        )
        db.commit()
    except (UnsupportedFileTypeError, EmptyUploadError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except BatchTooLargeError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc

    # After the relational commit on purpose: the forensic trail must never
    # reference a batch that does not exist, and a MongoDB outage must not
    # fail an upload that PostgreSQL already accepted. In the threadpool
    # because pymongo is blocking and this handler is a coroutine: with
    # MongoDB down, the driver's server-selection timeout must delay only
    # this request, not stall the event loop for every other client.
    await run_in_threadpool(
        record_rejections_best_effort,
        rejection_store,
        RejectionContext(
            batch_id=result.batch.id,
            source_filename=result.batch.original_filename,
            source_format=result.batch.original_filename.rsplit(".", maxsplit=1)[-1].lower(),
            file_checksum_sha256=result.batch.checksum_sha256,
        ),
        result.rejection_details,
    )

    return BatchResponse(
        id=result.batch.id,
        original_filename=result.batch.original_filename,
        status=result.batch.status,
        row_count=result.batch.row_count,
        accepted_row_count=result.accepted_row_count,
        rejected_row_count=result.rejected_row_count,
        rejected_rows=result.rejected_rows,
        checksum_sha256=result.batch.checksum_sha256,
        created_at=result.batch.created_at,
    )


@router.get("", response_model=list[BatchSummary])
def list_batches(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BatchSummary]:
    batches = BatchRepository(db).list_recent(limit=limit, offset=offset)
    return [BatchSummary.model_validate(b) for b in batches]


@router.get("/{batch_id}", response_model=BatchResponse)
def get_batch(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchResponse:
    batch = BatchRepository(db).get_by_id(batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found.")
    return BatchResponse(
        id=batch.id,
        original_filename=batch.original_filename,
        status=batch.status,
        row_count=batch.row_count,
        accepted_row_count=batch.accepted_row_count,
        rejected_row_count=batch.rejected_row_count,
        rejected_rows=batch.rejected_rows or [],
        checksum_sha256=batch.checksum_sha256,
        created_at=batch.created_at,
    )


@router.get("/{batch_id}/rejections", response_model=RejectedRowDetailPage)
def list_batch_rejections(
    batch_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    rejection_store: RejectionStore = Depends(get_rejection_store),
) -> RejectedRowDetailPage:
    """Forensic view of a batch's rejected rows: the original raw payloads
    and structured validation errors, served from MongoDB.

    Rows expire after ``MONGO_REJECTION_TTL_DAYS``; the relational summary
    in ``GET /batches/{id}`` is permanent.
    """
    if BatchRepository(db).get_by_id(batch_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found.")
    try:
        items = rejection_store.list_for_batch(batch_id, limit=limit, offset=offset)
        total = rejection_store.count_for_batch(batch_id)
    except RejectionStoreUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Rejection trail store is unavailable."
        ) from exc
    return RejectedRowDetailPage(
        batch_id=batch_id, total=total, limit=limit, offset=offset, items=items
    )
