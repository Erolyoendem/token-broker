from fastapi import APIRouter, HTTPException, Depends
from app.auth import require_api_key
from pydantic import BaseModel
from typing import List, Optional
import uuid

router = APIRouter(prefix="/swarm", tags=["swarm"])


class SwarmSubmitRequest(BaseModel):
    files: List[str]


class SwarmJobResponse(BaseModel):
    job_ids: List[str]


# In-Memory-Speicher (resets on restart – ersetzbar durch Supabase/Redis)
jobs: dict = {}


@router.post("/submit", response_model=SwarmJobResponse)
async def submit_jobs(
    request: SwarmSubmitRequest,
    user_id: str = Depends(require_api_key),
):
    job_ids = [f"job_{uuid.uuid4().hex[:8]}" for _ in request.files]
    for job_id, file in zip(job_ids, request.files):
        jobs[job_id] = {"status": "pending", "file": file, "user_id": user_id, "result": None}
    return {"job_ids": job_ids}


@router.get("/status/{job_id}")
async def get_status(job_id: str, user_id: str = Depends(require_api_key)):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return {"job_id": job_id, "status": job["status"], "file": job["file"]}


@router.get("/result/{job_id}")
async def get_result(job_id: str, user_id: str = Depends(require_api_key)):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if job["status"] != "completed":
        raise HTTPException(status_code=202, detail=f"Job not completed yet (status: {job['status']})")
    return {"job_id": job_id, "status": job["status"], "result": job["result"]}
