"""
FastAPI Job Broker for TouchDesigner -> ComfyUI Pipeline.

This server acts as a job broker between TouchDesigner and the ComfyUI worker.

Endpoints:
- POST /jobs - Submit a new job (image + optional prompt)
- GET /jobs/{job_id} - Get job status
- GET /jobs/{job_id}/result - Download result video
- DELETE /jobs/{job_id} - Cancel/delete a job
"""

import uuid
import time
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass, field, asdict

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import (
    API_HOST, API_PORT, JOBS_DIR, TEMP_DIR, COMFYUI_INPUT_DIR
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="TouchDesigner ComfyUI API",
    description="Job broker for TouchDesigner to ComfyUI pipeline",
    version="1.0.0"
)

# Add CORS middleware for cross-origin requests from TD
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class JobStatus(str, Enum):
    """Job status states."""
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    """Job data structure."""
    id: str
    status: JobStatus
    created_at: float
    input_image_path: str
    prompt: str = ""
    negative_prompt: Optional[str] = None
    seed: Optional[int] = None
    result_path: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "id": self.id,
            "status": self.status.value,
            "created_at": self.created_at,
            "prompt": self.prompt,
            "has_result": self.result_path is not None,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "processing_time": (
                self.completed_at - self.started_at 
                if self.started_at and self.completed_at else None
            )
        }


# In-memory job store (could be upgraded to Redis/SQLite)
jobs: Dict[str, Job] = {}


def cleanup_old_jobs(max_age_seconds: int = 3600):
    """Remove jobs older than max_age_seconds."""
    now = time.time()
    to_remove = []
    
    for job_id, job in jobs.items():
        if now - job.created_at > max_age_seconds:
            to_remove.append(job_id)
    
    for job_id in to_remove:
        job = jobs.pop(job_id, None)
        if job:
            # Clean up files
            try:
                if job.input_image_path and Path(job.input_image_path).exists():
                    Path(job.input_image_path).unlink()
                if job.result_path and Path(job.result_path).exists():
                    Path(job.result_path).unlink()
            except Exception as e:
                logger.warning(f"Error cleaning up job {job_id}: {e}")
    
    if to_remove:
        logger.info(f"Cleaned up {len(to_remove)} old jobs")


@app.post("/jobs")
async def create_job(
    image: UploadFile = File(...),
    prompt: str = Form(default=""),
    negative_prompt: Optional[str] = Form(default=None),
    seed: Optional[int] = Form(default=None)
):
    """
    Submit a new job for processing.
    
    Args:
        image: Input image file (PNG, JPG, etc.)
        prompt: Positive prompt for generation (default: empty)
        negative_prompt: Negative prompt (optional, uses workflow default if not provided)
        seed: Random seed (optional, random if not provided)
    
    Returns:
        Job ID and status
    """
    # Generate unique job ID
    job_id = str(uuid.uuid4())[:8]
    timestamp = int(time.time() * 1000)
    
    # Save uploaded image to ComfyUI input directory
    # Use unique filename to avoid conflicts
    file_ext = Path(image.filename).suffix if image.filename else ".png"
    input_filename = f"td_input_{job_id}_{timestamp}{file_ext}"
    input_path = COMFYUI_INPUT_DIR / input_filename
    
    try:
        # Ensure input directory exists
        COMFYUI_INPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Save uploaded file
        with open(input_path, "wb") as f:
            content = await image.read()
            f.write(content)
        
        logger.info(f"Saved input image: {input_path} ({len(content)} bytes)")
        
    except Exception as e:
        logger.error(f"Failed to save input image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save image: {e}")
    
    # Create job
    job = Job(
        id=job_id,
        status=JobStatus.QUEUED,
        created_at=time.time(),
        input_image_path=str(input_path),
        prompt=prompt,
        negative_prompt=negative_prompt,
        seed=seed
    )
    
    jobs[job_id] = job
    
    logger.info(f"Created job {job_id} with prompt: '{prompt[:50]}...' " if len(prompt) > 50 else f"Created job {job_id} with prompt: '{prompt}'")
    
    # Periodic cleanup
    if len(jobs) > 100:
        cleanup_old_jobs()
    
    return {
        "job_id": job_id,
        "status": job.status.value,
        "message": "Job queued for processing"
    }


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """
    Get the status of a job.
    
    Args:
        job_id: The job ID to check
    
    Returns:
        Job status and details
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    return jobs[job_id].to_dict()


@app.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str):
    """
    Download the result video for a completed job.
    
    Args:
        job_id: The job ID
    
    Returns:
        Video file download
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = jobs[job_id]
    
    if job.status != JobStatus.DONE:
        raise HTTPException(
            status_code=400, 
            detail=f"Job is not complete. Status: {job.status.value}"
        )
    
    if not job.result_path or not Path(job.result_path).exists():
        raise HTTPException(status_code=404, detail="Result file not found")
    
    result_path = Path(job.result_path)
    
    # Determine media type based on extension
    media_type = "video/mp4"
    if result_path.suffix.lower() == ".webm":
        media_type = "video/webm"
    elif result_path.suffix.lower() == ".gif":
        media_type = "image/gif"
    
    return FileResponse(
        path=result_path,
        media_type=media_type,
        filename=f"result_{job_id}{result_path.suffix}"
    )


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """
    Delete/cancel a job and its associated files.
    
    Args:
        job_id: The job ID to delete
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = jobs.pop(job_id)
    
    # Clean up files
    try:
        if job.input_image_path and Path(job.input_image_path).exists():
            Path(job.input_image_path).unlink()
        if job.result_path and Path(job.result_path).exists():
            Path(job.result_path).unlink()
    except Exception as e:
        logger.warning(f"Error cleaning up job files: {e}")
    
    return {"message": f"Job {job_id} deleted"}


@app.get("/jobs")
async def list_jobs(status: Optional[str] = None, limit: int = 50):
    """
    List all jobs, optionally filtered by status.
    
    Args:
        status: Filter by status (queued, running, done, error)
        limit: Maximum number of jobs to return
    """
    result = []
    
    for job in sorted(jobs.values(), key=lambda j: j.created_at, reverse=True):
        if status and job.status.value != status:
            continue
        result.append(job.to_dict())
        if len(result) >= limit:
            break
    
    return {
        "total": len(jobs),
        "returned": len(result),
        "jobs": result
    }


@app.get("/queue/next")
async def get_next_job():
    """
    Get the next queued job for processing (used by worker).
    
    Returns:
        Next queued job or empty response
    """
    for job in sorted(jobs.values(), key=lambda j: j.created_at):
        if job.status == JobStatus.QUEUED:
            return {
                "job_id": job.id,
                "input_image_path": job.input_image_path,
                "prompt": job.prompt,
                "negative_prompt": job.negative_prompt,
                "seed": job.seed
            }
    
    return {"job_id": None}


@app.post("/jobs/{job_id}/start")
async def mark_job_started(job_id: str):
    """
    Mark a job as started (used by worker).
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = jobs[job_id]
    job.status = JobStatus.RUNNING
    job.started_at = time.time()
    
    logger.info(f"Job {job_id} started processing")
    
    return {"status": "ok"}


@app.post("/jobs/{job_id}/complete")
async def mark_job_complete(
    job_id: str,
    result_path: str = Form(...)
):
    """
    Mark a job as complete with result path (used by worker).
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = jobs[job_id]
    job.status = JobStatus.DONE
    job.result_path = result_path
    job.completed_at = time.time()
    
    processing_time = job.completed_at - job.started_at if job.started_at else 0
    logger.info(f"Job {job_id} completed in {processing_time:.2f}s")
    
    return {"status": "ok"}


@app.post("/jobs/{job_id}/error")
async def mark_job_error(
    job_id: str,
    error_message: str = Form(...)
):
    """
    Mark a job as failed (used by worker).
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = jobs[job_id]
    job.status = JobStatus.ERROR
    job.error_message = error_message
    job.completed_at = time.time()
    
    logger.error(f"Job {job_id} failed: {error_message}")
    
    return {"status": "ok"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "jobs_count": len(jobs),
        "queued": sum(1 for j in jobs.values() if j.status == JobStatus.QUEUED),
        "running": sum(1 for j in jobs.values() if j.status == JobStatus.RUNNING),
        "done": sum(1 for j in jobs.values() if j.status == JobStatus.DONE),
        "error": sum(1 for j in jobs.values() if j.status == JobStatus.ERROR)
    }


def main():
    """Run the API server."""
    logger.info(f"Starting API server on {API_HOST}:{API_PORT}")
    uvicorn.run(
        "api_server:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()