"""
TouchDesigner Automatic Frame Loop - ComfyUI Pipeline

This script implements the full automatic cycle:
1. Capture frame from source TOP
2. Send to ComfyUI API
3. Wait for result (non-blocking polling)
4. Display result video
5. When video finishes → automatically capture and send next frame

SETUP IN TOUCHDESIGNER:
1. Create an Execute DAT
2. Set "Start" to "On" 
3. Copy this entire script into the Execute DAT
4. Create these operators:
   - A TOP as input (e.g., Movie File In, NDI In, Video Device In)
   - A Movie File In TOP called "result_video" for output
5. Configure SOURCE_TOP and SERVER_URL below

The script uses onFrameEnd() to poll for results without blocking the render loop.
"""

import os
import sys
import urllib.request
import urllib.parse
import json
import tempfile
import time

# =============================================================================
# CONFIGURATION - EDIT THESE VALUES
# =============================================================================

SERVER_URL = "https://beach-restructuring-penn-tvs.trycloudflare.com"  # Your Cloudflare tunnel URL
SOURCE_TOP = "source_top"       # Name of your input TOP
RESULT_TOP = "result_video"     # Name of Movie File In TOP for output
PROMPT = ""                     # Prompt for AI generation (empty = use workflow default)
POLL_INTERVAL_FRAMES = 15       # Check job status every N frames (~0.5 sec at 30fps)
TEMP_VIDEO_DIR = None           # Will use system temp, or set custom path

# =============================================================================
# STATE VARIABLES (don't edit)
# =============================================================================

_client = None
_current_job_id = None
_waiting_for_result = False
_frame_counter = 0
_temp_video_path = None
_initialized = False

# =============================================================================
# HTTP CLIENT (simplified, no external dependencies)
# =============================================================================

class SimpleClient:
    """Simple HTTP client for ComfyUI API."""
    
    def __init__(self, server_url):
        self.server_url = server_url.rstrip('/')
        self.timeout = 30
    
    def submit_frame(self, image_bytes, prompt="", filename="frame.png"):
        """Submit a frame for processing."""
        url = f"{self.server_url}/jobs"
        boundary = "----TDComfyBoundary"
        
        body = []
        body.append(f"--{boundary}".encode())
        body.append(f'Content-Disposition: form-data; name="image"; filename="{filename}"'.encode())
        body.append(b'Content-Type: application/octet-stream')
        body.append(b'')
        body.append(image_bytes)
        body.append(f"--{boundary}".encode())
        body.append(b'Content-Disposition: form-data; name="prompt"')
        body.append(b'')
        body.append(prompt.encode('utf-8'))
        body.append(f"--{boundary}--".encode())
        body.append(b'')
        
        data = b'\r\n'.join(body)
        
        req = urllib.request.Request(
            url, data=data,
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            result = json.loads(response.read())
            return result['job_id']
    
    def check_job(self, job_id):
        """Check job status."""
        url = f"{self.server_url}/jobs/{job_id}"
        with urllib.request.urlopen(url, timeout=self.timeout) as response:
            return json.loads(response.read())
    
    def get_result(self, job_id):
        """Download result video."""
        url = f"{self.server_url}/jobs/{job_id}/result"
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    
    def delete_job(self, job_id):
        """Delete job and cleanup."""
        url = f"{self.server_url}/jobs/{job_id}"
        req = urllib.request.Request(url, method='DELETE')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return True
        except:
            return False
    
    def health_check(self):
        """Check server health."""
        url = f"{self.server_url}/health"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read())
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}


def top_to_png_bytes(top_op):
    """Convert a TOP to PNG bytes."""
    temp_path = tempfile.mktemp(suffix='.png')
    try:
        top_op.save(temp_path)
        with open(temp_path, 'rb') as f:
            return f.read()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# =============================================================================
# MAIN LOOP FUNCTIONS
# =============================================================================

def initialize():
    """Initialize the client and temp paths."""
    global _client, _temp_video_path, _initialized
    
    if _initialized:
        return True
    
    try:
        _client = SimpleClient(SERVER_URL)
        
        # Check server health
        health = _client.health_check()
        if health.get('status') == 'healthy':
            print(f"[ComfyUI] Connected to server: {SERVER_URL}")
        else:
            print(f"[ComfyUI] Warning: Server status: {health}")
        
        # Set up temp video path
        if TEMP_VIDEO_DIR:
            os.makedirs(TEMP_VIDEO_DIR, exist_ok=True)
            _temp_video_path = os.path.join(TEMP_VIDEO_DIR, "comfy_result.mp4")
        else:
            _temp_video_path = os.path.join(tempfile.gettempdir(), "td_comfy_result.mp4")
        
        print(f"[ComfyUI] Temp video path: {_temp_video_path}")
        _initialized = True
        return True
        
    except Exception as e:
        print(f"[ComfyUI] Initialization error: {e}")
        return False


def capture_and_send_frame():
    """Capture current frame and send to API."""
    global _current_job_id, _waiting_for_result
    
    try:
        source = op(SOURCE_TOP)
        if source is None:
            print(f"[ComfyUI] ERROR: Source TOP '{SOURCE_TOP}' not found!")
            return False
        
        # Capture frame
        image_bytes = top_to_png_bytes(source)
        print(f"[ComfyUI] Captured frame: {len(image_bytes)} bytes")
        
        # Submit to API
        _current_job_id = _client.submit_frame(image_bytes, prompt=PROMPT)
        _waiting_for_result = True
        print(f"[ComfyUI] Submitted job: {_current_job_id}")
        
        return True
        
    except Exception as e:
        print(f"[ComfyUI] Error sending frame: {e}")
        _waiting_for_result = False
        return False


def check_and_process_result():
    """Check job status and handle completion."""
    global _current_job_id, _waiting_for_result
    
    if not _current_job_id:
        return
    
    try:
        status = _client.check_job(_current_job_id)
        job_status = status.get('status', 'unknown')
        
        if job_status == 'done':
            # Download result
            print(f"[ComfyUI] Job {_current_job_id} complete, downloading result...")
            video_bytes = _client.get_result(_current_job_id)
            
            # Save to temp file
            with open(_temp_video_path, 'wb') as f:
                f.write(video_bytes)
            print(f"[ComfyUI] Saved result: {_temp_video_path} ({len(video_bytes)} bytes)")
            
            # Update Movie File In TOP
            result_op = op(RESULT_TOP)
            if result_op:
                result_op.par.file = _temp_video_path
                result_op.par.cuepoint = 0
                result_op.par.play = True
                print(f"[ComfyUI] Playing result in '{RESULT_TOP}'")
            else:
                print(f"[ComfyUI] Warning: Result TOP '{RESULT_TOP}' not found")
            
            # Cleanup job on server
            _client.delete_job(_current_job_id)
            
            # Reset state - ready for next frame
            _current_job_id = None
            _waiting_for_result = False
            
        elif job_status == 'error':
            error_msg = status.get('error_message', 'Unknown error')
            print(f"[ComfyUI] Job {_current_job_id} FAILED: {error_msg}")
            _current_job_id = None
            _waiting_for_result = False
            
        # queued/running - keep waiting
            
    except Exception as e:
        print(f"[ComfyUI] Error checking job: {e}")


def should_send_new_frame():
    """Determine if we should capture and send a new frame."""
    if _waiting_for_result:
        return False
    
    # Check if result video finished playing
    result_op = op(RESULT_TOP)
    if result_op and result_op.par.file != '':
        # If video exists and finished playing (or hasn't started), send new frame
        # You can customize this logic based on your needs
        pass
    
    return True


# =============================================================================
# TOUCHDESIGNER CALLBACKS
# =============================================================================

def onSetupParameters(scriptOp):
    """Called when script needs setup."""
    pass


def onPulse(par):
    """Called when a pulse parameter is pressed."""
    if par.name == 'Sendframe':
        if initialize():
            capture_and_send_frame()
    elif par.name == 'Checkhealth':
        if _client:
            print(f"[ComfyUI] Health: {_client.health_check()}")


def onCook(scriptOp):
    """
    Called every frame - main loop logic.
    
    This implements the automatic cycle:
    1. If not waiting → capture and send frame
    2. If waiting → poll for result (every POLL_INTERVAL_FRAMES)
    3. When result arrives → load video
    4. Video plays, then loop back to step 1
    """
    global _frame_counter
    
    # Initialize on first run
    if not initialize():
        return
    
    _frame_counter += 1
    
    if _waiting_for_result:
        # Poll for result at configured interval
        if _frame_counter % POLL_INTERVAL_FRAMES == 0:
            check_and_process_result()
    else:
        # Ready to send new frame
        if should_send_new_frame():
            capture_and_send_frame()


# =============================================================================
# MANUAL TESTING (for running outside TD)
# =============================================================================

if __name__ == "__main__":
    print("This script is meant to run inside TouchDesigner.")
    print(f"Server URL: {SERVER_URL}")
    
    # Quick test
    client = SimpleClient(SERVER_URL)
    health = client.health_check()
    print(f"Server health: {health}")