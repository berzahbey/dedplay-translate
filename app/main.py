import os
import shutil
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .export import build
from .worker import worker

app = FastAPI(title="Dedplay Translate")
STATIC = os.path.join(os.path.dirname(__file__), "static")
ALLOWED = {".epub", ".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
LANGS = {"auto", "ar", "en", "fr"}
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(os.path.join(STATIC, "icon-32.png"))


@app.on_event("startup")
def startup():
    db.init()
    worker.start()


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/status")
def status():
    return worker.status


def job_view(j):
    d = dict(j)
    d["eta"] = None
    if d["status"] in ("running", "queued", "paused") and d["done_chars"] and d["elapsed"]:
        rate = d["done_chars"] / d["elapsed"]
        d["eta"] = int((d["total_chars"] - d["done_chars"]) / rate) if rate else None
    return d


@app.get("/api/jobs")
def jobs():
    return [job_view(j) for j in db.list_jobs()]


@app.post("/api/jobs")
def create_job(file: UploadFile = File(...), src_lang: str = Form("auto")):
    name = os.path.basename(file.filename or "dosya")
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, "Bu dosya türü desteklenmiyor. EPUB, PDF, DOCX, TXT, PNG veya JPEG yükleyin.")
    if src_lang not in LANGS:
        src_lang = "auto"
    job_id = db.create_job(name, src_lang)
    with open(db.upload_path(job_id, name), "wb") as f:
        shutil.copyfileobj(file.file, f)
    db.set_status(job_id, "queued")
    return {"id": job_id}


@app.post("/api/jobs/{job_id}/pause")
def pause(job_id: int):
    db.set_status(job_id, "paused", only_from=("queued", "running"))
    return {"ok": True}


@app.post("/api/jobs/{job_id}/resume")
def resume(job_id: int):
    db.set_status(job_id, "queued", only_from=("paused", "error"))
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete(job_id: int):
    db.delete_job(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/preview")
def preview(job_id: int):
    return db.recent_pairs(job_id)


@app.get("/api/jobs/{job_id}/download")
def download(job_id: int, fmt: str = "epub", bilingual: int = 0):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    data, media, filename = build(job, db.all_segments(job_id), fmt, bool(bilingual))
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return Response(data, media_type=media, headers=headers)


class Term(BaseModel):
    src: str
    tgt: str


@app.get("/api/glossary")
def glossary():
    return db.glossary()


@app.post("/api/glossary")
def add_term(t: Term):
    if not t.src.strip() or not t.tgt.strip():
        raise HTTPException(400, "Kaynak terim ve Türkçe karşılığı boş olamaz")
    db.add_term(t.src, t.tgt)
    return {"ok": True}


@app.delete("/api/glossary/{term_id}")
def delete_term(term_id: int):
    db.delete_term(term_id)
    return {"ok": True}
