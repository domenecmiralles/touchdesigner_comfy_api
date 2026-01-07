"""
TouchDesigner Client for ComfyUI API Pipeline.

This module provides a client class for TouchDesigner to interact with the 
ComfyUI job broker API. It's designed to be used in TouchDesigner's Execute DAT
or Script CHOP/TOP.

Usage in TouchDesigner:
    
    # In an Execute DAT or Script:
    from touchdesigner_client import TDComfyClient
    
    # Initialize client (once)
    client = TDComfyClient("http://YOUR_SERVER_IP:8080")
    
    # Submit a frame
    job_id = client.submit_frame(top_to_bytes(op('moviefilein1')))
    
    # Check status (call periodically)
    status = client.check_job(job_id)
    
    # When done, get result
    if status['status'] == 'done':
        video_bytes = client.get_result(job_id)
        # Use video_bytes in TD...
"""

import urllib.request
import urllib.parse
import json
import io
from typing import Optional, Dict, Any, Tuple


class TDComfyClient:
    """
    Client for TouchDesigner to communicate with the ComfyUI job broker.
    
    This client is designed to be non-blocking friendly - each method makes
    a single HTTP request and returns immediately.
    """
    
    def __init__(self, server_url: str = "http://127.0.0.1:8080"):
        """
        Initialize the client.
        
        Args:
            server_url: Base URL of the API server (e.g., "http://192.168.1.100:8080")
        """
        self.server_url = server_url.rstrip('/')
        self.current_job_id: Optional[str] = None
        self.timeout = 30  # HTTP timeout in seconds
    
    def submit_frame(
        self,
        image_bytes: bytes,
        prompt: str = "",
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        filename: str = "frame.png"
    ) -> str:
        """
        Submit a frame for processing.
        
        Args:
            image_bytes: Raw image bytes (PNG, JPG, etc.)
            prompt: Positive prompt for generation (default: empty)
            negative_prompt: Negative prompt (optional)
            seed: Random seed (optional)
            filename: Filename hint for the upload
            
        Returns:
            Job ID string
        """
        url = f"{self.server_url}/jobs"
        
        # Build multipart form data
        boundary = "----TDComfyBoundary"
        
        body = []
        
        # Add image file
        body.append(f"--{boundary}".encode())
        body.append(f'Content-Disposition: form-data; name="image"; filename="{filename}"'.encode())
        body.append(b'Content-Type: application/octet-stream')
        body.append(b'')
        body.append(image_bytes)
        
        # Add prompt
        body.append(f"--{boundary}".encode())
        body.append(b'Content-Disposition: form-data; name="prompt"')
        body.append(b'')
        body.append(prompt.encode('utf-8'))
        
        # Add negative prompt if provided
        if negative_prompt is not None:
            body.append(f"--{boundary}".encode())
            body.append(b'Content-Disposition: form-data; name="negative_prompt"')
            body.append(b'')
            body.append(negative_prompt.encode('utf-8'))
        
        # Add seed if provided
        if seed is not None:
            body.append(f"--{boundary}".encode())
            body.append(b'Content-Disposition: form-data; name="seed"')
            body.append(b'')
            body.append(str(seed).encode('utf-8'))
        
        # End boundary
        body.append(f"--{boundary}--".encode())
        body.append(b'')
        
        # Join with CRLF
        data = b'\r\n'.join(body)
        
        # Make request
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            },
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            result = json.loads(response.read())
            job_id = result['job_id']
            self.current_job_id = job_id
            return job_id
    
    def check_job(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Check the status of a job.
        
        Args:
            job_id: Job ID to check (uses current_job_id if not provided)
            
        Returns:
            Dictionary with job status and details:
            {
                'id': str,
                'status': 'queued' | 'running' | 'done' | 'error',
                'has_result': bool,
                'error_message': str | None,
                'processing_time': float | None
            }
        """
        if job_id is None:
            job_id = self.current_job_id
        
        if job_id is None:
            raise ValueError("No job ID provided and no current job")
        
        url = f"{self.server_url}/jobs/{job_id}"
        
        with urllib.request.urlopen(url, timeout=self.timeout) as response:
            return json.loads(response.read())
    
    def get_result(self, job_id: Optional[str] = None) -> bytes:
        """
        Download the result video for a completed job.
        
        Args:
            job_id: Job ID to get result for (uses current_job_id if not provided)
            
        Returns:
            Video file bytes
        """
        if job_id is None:
            job_id = self.current_job_id
        
        if job_id is None:
            raise ValueError("No job ID provided and no current job")
        
        url = f"{self.server_url}/jobs/{job_id}/result"
        
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    
    def delete_job(self, job_id: Optional[str] = None) -> bool:
        """
        Delete a job and its files.
        
        Args:
            job_id: Job ID to delete (uses current_job_id if not provided)
            
        Returns:
            True if successful
        """
        if job_id is None:
            job_id = self.current_job_id
        
        if job_id is None:
            raise ValueError("No job ID provided and no current job")
        
        url = f"{self.server_url}/jobs/{job_id}"
        
        req = urllib.request.Request(url, method='DELETE')
        
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            if job_id == self.current_job_id:
                self.current_job_id = None
            return response.status == 200
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check server health and queue status.
        
        Returns:
            Dictionary with server status
        """
        url = f"{self.server_url}/health"
        
        with urllib.request.urlopen(url, timeout=self.timeout) as response:
            return json.loads(response.read())
    
    def is_ready_for_next(self) -> bool:
        """
        Check if the client is ready to submit a new frame.
        
        Returns True if:
        - No current job, or
        - Current job is complete (done or error)
        """
        if self.current_job_id is None:
            return True
        
        try:
            status = self.check_job()
            return status['status'] in ('done', 'error')
        except Exception:
            return True


# =============================================================================
# TouchDesigner Helper Functions
# =============================================================================

def top_to_png_bytes(top_op) -> bytes:
    """
    Convert a TouchDesigner TOP to PNG bytes.
    
    Args:
        top_op: A TOP operator (e.g., op('moviefilein1'))
        
    Returns:
        PNG image bytes
    
    Usage in TD:
        image_bytes = top_to_png_bytes(op('moviefilein1'))
    """
    # Use TD's built-in save method to memory
    import tempfile
    import os
    
    # Create temp file
    temp_path = tempfile.mktemp(suffix='.png')
    
    try:
        # Save TOP to temp file
        top_op.save(temp_path)
        
        # Read bytes
        with open(temp_path, 'rb') as f:
            return f.read()
    finally:
        # Clean up
        if os.path.exists(temp_path):
            os.remove(temp_path)


def bytes_to_file_top(video_bytes: bytes, output_path: str) -> str:
    """
    Save video bytes to a file for use with Movie File In TOP.
    
    Args:
        video_bytes: Video file bytes
        output_path: Path to save the video
        
    Returns:
        Path to the saved file
    """
    with open(output_path, 'wb') as f:
        f.write(video_bytes)
    return output_path


# =============================================================================
# Example TouchDesigner Integration
# =============================================================================

EXAMPLE_EXECUTE_DAT = '''
# ============================================================================
# Example Execute DAT Script for TouchDesigner
# ============================================================================
# 
# This script shows how to integrate the ComfyUI pipeline into TouchDesigner.
# 
# Setup:
# 1. Copy touchdesigner_client.py to your TD project folder or add to path
# 2. Create an Execute DAT and paste this code
# 3. Connect a TOP to 'source_top' reference
# 4. Create a Movie File In TOP called 'result_video' for output
# 
# The script will:
# - Capture frames from source_top
# - Send to ComfyUI for processing
# - Load results into result_video
# ============================================================================

import os
import sys

# Add the touchdesigner_comfy_api folder to path
# Adjust this path to match your setup
API_PATH = "/path/to/touchdesigner_comfy_api"
if API_PATH not in sys.path:
    sys.path.insert(0, API_PATH)

from touchdesigner_client import TDComfyClient, top_to_png_bytes

# Configuration
SERVER_URL = "http://YOUR_SERVER_IP:8080"  # Change to your server IP
SOURCE_TOP = "source_top"  # Name of input TOP
RESULT_TOP = "result_video"  # Name of Movie File In TOP for result
TEMP_VIDEO_PATH = "/tmp/td_comfy_result.mp4"  # Temp path for result video
PROMPT = ""  # Your prompt here (empty = no prompt)

# Global state
client = None
current_job = None
waiting_for_result = False

def onSetupParameters(scriptOp):
    """Called when script parameters need setup."""
    pass

def onPulse(par):
    """Called when a pulse parameter is triggered."""
    pass

def onCook(scriptOp):
    """Called each frame - main logic goes here."""
    global client, current_job, waiting_for_result
    
    # Initialize client once
    if client is None:
        client = TDComfyClient(SERVER_URL)
        print(f"Initialized ComfyUI client: {SERVER_URL}")
    
    # State machine
    if not waiting_for_result:
        # Ready to send new frame
        if client.is_ready_for_next():
            try:
                # Get source TOP
                source = op(SOURCE_TOP)
                if source is None:
                    return
                
                # Capture frame
                image_bytes = top_to_png_bytes(source)
                
                # Submit to API
                job_id = client.submit_frame(image_bytes, prompt=PROMPT)
                current_job = job_id
                waiting_for_result = True
                print(f"Submitted frame, job: {job_id}")
                
            except Exception as e:
                print(f"Error submitting frame: {e}")
    
    else:
        # Waiting for result
        try:
            status = client.check_job(current_job)
            
            if status['status'] == 'done':
                # Download result
                video_bytes = client.get_result(current_job)
                
                # Save to temp file
                with open(TEMP_VIDEO_PATH, 'wb') as f:
                    f.write(video_bytes)
                
                # Update Movie File In TOP
                result_op = op(RESULT_TOP)
                if result_op:
                    result_op.par.file = TEMP_VIDEO_PATH
                    result_op.par.cuepoint = 0  # Restart from beginning
                    result_op.par.play = True
                
                print(f"Job {current_job} complete, loaded result")
                
                # Clean up job
                client.delete_job(current_job)
                current_job = None
                waiting_for_result = False
                
            elif status['status'] == 'error':
                print(f"Job {current_job} failed: {status.get('error_message')}")
                current_job = None
                waiting_for_result = False
                
        except Exception as e:
            print(f"Error checking job: {e}")
'''


# =============================================================================
# Standalone testing
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # Simple test without TD
    print("TouchDesigner ComfyUI Client")
    print("=" * 50)
    
    # Default server URL
    server_url = "http://127.0.0.1:8080"
    if len(sys.argv) > 1:
        server_url = sys.argv[1]
    
    print(f"Server: {server_url}")
    
    client = TDComfyClient(server_url)
    
    # Test health check
    try:
        health = client.health_check()
        print(f"Server health: {health}")
    except Exception as e:
        print(f"Server not reachable: {e}")
        sys.exit(1)
    
    # If a test image is provided
    if len(sys.argv) > 2:
        image_path = sys.argv[2]
        print(f"\nTesting with image: {image_path}")
        
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        
        # Submit job
        job_id = client.submit_frame(image_bytes, prompt="test prompt")
        print(f"Submitted job: {job_id}")
        
        # Wait for completion
        import time
        while True:
            status = client.check_job(job_id)
            print(f"Status: {status['status']}")
            
            if status['status'] == 'done':
                print("Job complete!")
                result = client.get_result(job_id)
                output_path = f"result_{job_id}.mp4"
                with open(output_path, 'wb') as f:
                    f.write(result)
                print(f"Saved result to: {output_path}")
                break
            
            elif status['status'] == 'error':
                print(f"Job failed: {status.get('error_message')}")
                break
            
            time.sleep(1)
    
    print("\nDone!")