import os, tempfile
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Import, User
from app.security import get_current_user
from app.config import get_settings
from app.worker import run_import

router = APIRouter(prefix="/api/imports", tags=["imports"])

def _serialize(imp: Import) -> dict:
    return {
        "id": imp.id, "filename": imp.filename, "status": imp.status,
        "error_message": imp.error_message, "record_count": imp.record_count,
        "created_at": imp.created_at.isoformat() if imp.created_at else None,
        "completed_at": imp.completed_at.isoformat() if imp.completed_at else None,
    }

@router.post("", status_code=201)
async def create_import(bg: BackgroundTasks, file: UploadFile = File(...),
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    name = (file.filename or "").lower()
    if not (name.endswith(".xml") or name.endswith(".zip")):
        raise HTTPException(status_code=400, detail="Upload an export.xml or export.zip")
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    suffix = ".zip" if name.endswith(".zip") else ".xml"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    size = 0
    with os.fdopen(fd, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                out.close(); os.remove(tmp_path)
                raise HTTPException(status_code=413, detail="File too large")
            out.write(chunk)
    imp = Import(user_id=user.id, filename=file.filename or "export", status="pending")
    db.add(imp); db.commit(); db.refresh(imp)
    bg.add_task(run_import, imp.id, tmp_path)
    return {"import_id": imp.id, "status": imp.status}

@router.get("")
def list_imports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Import).filter(Import.user_id == user.id).order_by(Import.id.desc()).all()
    return [_serialize(i) for i in rows]

@router.get("/{import_id}")
def get_import(import_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    imp = db.get(Import, import_id)
    if not imp or imp.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize(imp)
