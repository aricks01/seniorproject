"""StegApp backend — FastAPI wrapper around steghide / stegseek.

Implements the API contract that frontend/common.js already speaks:

    GET  /api/wordlists            -> ["rockyou.txt", ...]
    POST /api/embed    (multipart) -> file blob            (cover, secret, passphrase)
    POST /api/extract  (multipart) -> file blob            (stego, passphrase)
    POST /api/detect   (multipart) -> { job_id }  then poll
    POST /api/crack    (multipart) -> { job_id }  then poll (needs X-API-Key)
    GET  /api/jobs/{id}            -> { state, percent?, result?, passphrase?, download? }
    POST /api/jobs/{id}/cancel     -> { ok: true }
    GET  /api/download/{id}        -> extracted payload from a solved crack

The frontend is also served from this app (StaticFiles mount) so everything is
one origin and there are no CORS concerns in local use.

Run:
    cd backend
    pip install -r requirements.txt
    uvicorn app:app --reload --port 8080
Then open http://localhost:8080/
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
import stego
from jobs import Job, jobs

app = FastAPI(title="StegApp API", version="1.0")

# Allow a separately-hosted frontend (e.g. on Render) to call this backend.
# Configured via STEGAPP_CORS_ORIGINS; defaults to "*". No cookies are used
# (auth is the X-API-Key header), so credentials stay disabled.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # Let the cross-origin frontend read the suggested download filename.
    expose_headers=["Content-Disposition"],
)


# --------------------------------------------------------------- utilities --
def _save_upload(up: UploadFile, dest_dir: Path) -> Path:
    """Persist an UploadFile to dest_dir, returning the path. Name is sanitized
    to a bare basename to avoid path traversal."""
    safe = Path(up.filename or "upload").name or "upload"
    dest = dest_dir / safe
    with dest.open("wb") as f:
        shutil.copyfileobj(up.file, f)
    return dest


def _check_api_key(key: str | None) -> None:
    key = (key or "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="API key required (X-API-Key header)")
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")


def _require_tool(name: str) -> None:
    if not config.tools_available().get(name):
        raise HTTPException(
            status_code=503,
            detail=f"{name} is not installed on the server (expected on a Kali host)",
        )


# ------------------------------------------------------------------ health --
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "tools": config.tools_available()}


@app.get("/api/wordlists")
def wordlists() -> list[str]:
    return config.list_wordlists()


# ------------------------------------------------------------------- embed --
@app.post("/api/embed")
def embed(
    cover: UploadFile = File(...),
    secret: UploadFile = File(...),
    passphrase: str = Form(""),
) -> FileResponse:
    ext = Path(cover.filename or "").suffix.lower()
    if ext not in config.ALLOWED_COVER_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported cover format '{ext}'. Use one of: "
                   + ", ".join(sorted(config.ALLOWED_COVER_EXT)),
        )
    _require_tool("steghide")
    work = Path(tempfile.mkdtemp(dir=config.WORK_DIR))
    cover_p = _save_upload(cover, work)
    secret_p = _save_upload(secret, work)
    out_p = work / ("stego_" + cover_p.name)
    try:
        stego.embed(cover_p, secret_p, out_p, passphrase)
    except stego.StegoError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return FileResponse(out_p, filename=out_p.name,
                        media_type="application/octet-stream")


# ----------------------------------------------------------------- extract --
@app.post("/api/extract")
def extract(
    stego_file: UploadFile = File(..., alias="stego"),
    passphrase: str = Form(""),
) -> FileResponse:
    _require_tool("steghide")
    work = Path(tempfile.mkdtemp(dir=config.WORK_DIR))
    stego_p = _save_upload(stego_file, work)
    out_p = work / "extracted.bin"
    try:
        stego.extract(stego_p, out_p, passphrase)
    except stego.StegoError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return FileResponse(out_p, filename="extracted.bin",
                        media_type="application/octet-stream")


# ------------------------------------------------------------------ detect --
@app.post("/api/detect")
def detect(stego_file: UploadFile = File(..., alias="stego")) -> dict:
    _require_tool("stegseek")
    work = Path(tempfile.mkdtemp(dir=config.WORK_DIR))
    stego_p = _save_upload(stego_file, work)

    def work_fn(job: Job) -> dict:
        present = stego.detect(stego_p, proc_sink=job._proc_sink)
        shutil.rmtree(work, ignore_errors=True)
        return {"result": "found" if present else "not_found"}

    job = jobs.submit("detect", work_fn)
    return {"job_id": job.id}


# ------------------------------------------------------------------- crack --
@app.post("/api/crack")
def crack(
    stego_file: UploadFile = File(..., alias="stego"),
    wordlist_name: str = Form(""),
    wordlist: UploadFile | None = File(None),
    x_api_key: str | None = Header(None),
) -> dict:
    _check_api_key(x_api_key)
    _require_tool("stegseek")

    work = Path(tempfile.mkdtemp(dir=config.WORK_DIR))

    # An uploaded wordlist overrides the named server wordlist.
    if wordlist is not None and wordlist.filename:
        wl_path = _save_upload(wordlist, work)
    else:
        wl_path = config.resolve_wordlist(wordlist_name)
        if wl_path is None:
            shutil.rmtree(work, ignore_errors=True)
            raise HTTPException(status_code=400,
                                detail="choose a valid server wordlist or upload one")

    stego_p = _save_upload(stego_file, work)

    out_p = work / "extracted.bin"

    def work_fn(job: Job) -> dict:
        res = stego.crack(stego_p, Path(wl_path), out_p, proc_sink=job._proc_sink)
        if res.found:
            # Keep the extracted file around for /api/download/{id}.
            return {
                "result": "found",
                "passphrase": res.passphrase,
                "download": f"/api/download/{job.id}",
                "_file": str(res.output_path or out_p),
                "_name": res.original_name or "extracted.bin",
            }
        shutil.rmtree(work, ignore_errors=True)
        return {"result": "not_found"}

    job = jobs.submit("crack", work_fn)
    return {"job_id": job.id}


# -------------------------------------------------------------------- jobs --
@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job")
    view = job.view()
    # Don't leak internal bookkeeping fields to the client.
    view.pop("_file", None)
    view.pop("_name", None)
    return JSONResponse(view)


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict:
    if not jobs.cancel(job_id):
        raise HTTPException(status_code=404, detail="unknown job")
    return {"ok": True}


@app.get("/api/download/{job_id}")
def download(job_id: str) -> FileResponse:
    job = jobs.get(job_id)
    if not job or job.result.get("result") != "found":
        raise HTTPException(status_code=404, detail="nothing to download")
    path = job.result.get("_file")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="extracted file is gone")
    return FileResponse(path, filename=job.result.get("_name", "extracted.bin"),
                        media_type="application/octet-stream")


# ---- Serve the frontend last so /api/* routes take precedence --------------
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True),
          name="frontend")
