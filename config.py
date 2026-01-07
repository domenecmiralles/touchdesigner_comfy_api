"""
Configuration settings for TouchDesigner ComfyUI API pipeline.
"""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.resolve()
WORKFLOWS_DIR = BASE_DIR / "workflows"
JOBS_DIR = BASE_DIR / "jobs"
TEMP_DIR = BASE_DIR / "temp"

# ComfyUI settings
COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1")
COMFYUI_PORT = int(os.environ.get("COMFYUI_PORT", "8111"))
COMFYUI_SERVER = f"{COMFYUI_HOST}:{COMFYUI_PORT}"

# ComfyUI directories (for file access)
COMFYUI_DIR = BASE_DIR.parent / "ComfyUI"
COMFYUI_INPUT_DIR = COMFYUI_DIR / "input"
COMFYUI_OUTPUT_DIR = COMFYUI_DIR / "output"

# API Server settings
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8080"))

# Worker settings
WORKER_POLL_INTERVAL = float(os.environ.get("WORKER_POLL_INTERVAL", "0.5"))  # seconds
COMFYUI_POLL_INTERVAL = float(os.environ.get("COMFYUI_POLL_INTERVAL", "1.0"))  # seconds
JOB_TIMEOUT = float(os.environ.get("JOB_TIMEOUT", "600"))  # 10 minutes max

# Default workflow
DEFAULT_WORKFLOW = "zimage.json"

# Workflow node IDs (from zimage.json - image generation)
WORKFLOW_NODES = {
    "image_input": "70",        # VHS_LoadImagePath - image field
    "positive_prompt": "49",    # CLIPTextEncode - text field
    "negative_prompt": None,    # Not used in this workflow
    "image_output": "54",       # SaveImage - filename_prefix field
    "seed": "53",               # KSampler - seed field
}

# Create directories
JOBS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)
