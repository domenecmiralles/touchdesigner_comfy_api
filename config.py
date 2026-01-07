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
DEFAULT_WORKFLOW = "ltxv_image_to_video.json"

# Workflow node IDs (from ltxv_image_to_video.json)
WORKFLOW_NODES = {
    "image_input": "240",      # VHS_LoadImagePath - image field
    "positive_prompt": "6",     # CLIPTextEncode - text field
    "negative_prompt": "7",     # CLIPTextEncode - text field
    "video_output": "241",      # VHS_VideoCombine - filename_prefix field
    "seed": "72",               # SamplerCustom - noise_seed field
    "img_to_video": "77",       # LTXVImgToVideo - dimensions and settings
}

# Create directories
JOBS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)