"""
ComfyUI Client for TouchDesigner - THREADED VERSION

Uses background threads for all HTTP operations.
TouchDesigner main loop is NEVER blocked.

SETUP:
1. Create source TOP named "source_top" (Video Device In)
2. Create Movie File In TOP named "output"
3. Create Execute DAT, paste this script
4. Turn on "Frame Start" in Execute DAT parameters
"""

import os
import urllib.request
import json
import ssl
import tempfile
import threading
from queue import Queue, Empty

# Disable SSL verification
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVER_URL = "https://taken-breach-laden-mason.trycloudflare.com"
SOURCE_TOP_NAME = "source_top"
OUTPUT_TOP_NAME = "output"
PROMPT = ""

# Paths
FRAME_PATH = os.path.join(tempfile.gettempdir(), "td_comfy_frame.png")
# Double-buffer for output (alternate between two files so TD sees a "new" file)
# Using .png extension since zimage outputs images
RESULT_PATH_A = os.path.join(tempfile.gettempdir(), "td_comfy_result_A.png")
RESULT_PATH_B = os.path.join(tempfile.gettempdir(), "td_comfy_result_B.png")

# =============================================================================
# SHARED STATE (thread-safe via queues)
# =============================================================================

# Commands from main thread to worker thread
_command_queue = Queue()

# Results from worker thread to main thread  
_result_queue = Queue()

# Simple flags (atomic reads in Python)
_is_processing = False
_worker_thread = None
_current_buffer = "A"  # Toggle between A and B

def log(msg):
    print(f"[Comfy] {msg}")

# =============================================================================
# HTTP FUNCTIONS (called in worker thread)
# =============================================================================

def http_post_file(url, file_path, prompt=""):
    with open(file_path, 'rb') as f:
        file_data = f.read()
    
    boundary = "----TDBoundary"
    body = b'\r\n'.join([
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="image"; filename="frame.png"',
        b'Content-Type: image/png',
        b'',
        file_data,
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="prompt"',
        b'',
        prompt.encode(),
        f"--{boundary}--".encode(),
        b''
    ])
    
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
        return json.loads(resp.read())

def http_get(url):
    with urllib.request.urlopen(url, timeout=10, context=ssl_context) as resp:
        return json.loads(resp.read())

def http_get_binary(url):
    with urllib.request.urlopen(url, timeout=60, context=ssl_context) as resp:
        return resp.read()

# =============================================================================
# WORKER THREAD - Does all the slow network stuff
# =============================================================================

def worker_loop():
    """Background worker that handles HTTP operations."""
    global _is_processing, _current_buffer
    
    log("Worker thread started")
    
    while True:
        try:
            # Wait for a command
            cmd = _command_queue.get(timeout=1)
            
            if cmd is None:  # Shutdown signal
                log("Worker thread stopping")
                break
            
            if cmd == "SUBMIT":
                _is_processing = True
                try:
                    # 1. Submit the frame
                    log("Submitting frame...")
                    result = http_post_file(f"{SERVER_URL}/jobs", FRAME_PATH, PROMPT)
                    job_id = result['job_id']
                    log(f"Job submitted: {job_id}")
                    
                    # 2. Poll until done
                    while True:
                        status = http_get(f"{SERVER_URL}/jobs/{job_id}")
                        job_status = status.get('status')
                        
                        if job_status == 'done':
                            # 3. Download result to alternate buffer
                            # Toggle buffer so TD sees a "new" file
                            if _current_buffer == "A":
                                result_path = RESULT_PATH_B
                                _current_buffer = "B"
                            else:
                                result_path = RESULT_PATH_A
                                _current_buffer = "A"
                            
                            log(f"Downloading to buffer {_current_buffer}...")
                            video = http_get_binary(f"{SERVER_URL}/jobs/{job_id}/result")
                            with open(result_path, 'wb') as f:
                                f.write(video)
                            log(f"Downloaded {len(video)} bytes to {result_path}")
                            
                            # Signal main thread with the new path
                            _result_queue.put(("DONE", result_path))
                            break
                            
                        elif job_status == 'error':
                            log(f"Job failed: {status.get('error_message')}")
                            _result_queue.put(("ERROR", status.get('error_message')))
                            break
                        
                        # Still processing, wait a bit
                        import time
                        time.sleep(0.5)
                    
                except Exception as e:
                    log(f"Worker error: {e}")
                    _result_queue.put(("ERROR", str(e)))
                finally:
                    _is_processing = False
                    
        except Empty:
            pass  # No command, loop again
        except Exception as e:
            log(f"Worker exception: {e}")

# =============================================================================
# MAIN THREAD FUNCTIONS (called from TD)
# =============================================================================

def start_worker():
    """Start the background worker thread."""
    global _worker_thread
    
    if _worker_thread is not None and _worker_thread.is_alive():
        return  # Already running
    
    _worker_thread = threading.Thread(target=worker_loop, daemon=True)
    _worker_thread.start()
    log("Worker thread launched")

def stop_worker():
    """Stop the worker thread."""
    _command_queue.put(None)

def request_frame_processing():
    """Request the worker to process current frame."""
    global _is_processing
    
    if _is_processing:
        return  # Already processing, skip
    
    # Save frame (this is fast, OK to do in main thread)
    source = op(SOURCE_TOP_NAME)
    if source is None:
        return
    
    try:
        source.save(FRAME_PATH)
        log("Frame saved, sending to worker...")
        _command_queue.put("SUBMIT")
    except Exception as e:
        log(f"Save error: {e}")

def check_for_results():
    """Check if worker has produced results (non-blocking)."""
    try:
        result_type, result_data = _result_queue.get_nowait()
        
        if result_type == "DONE":
            log("Result ready, loading...")
            load_result_file(result_data)
            
        elif result_type == "ERROR":
            log(f"Error received: {result_data}")
            
    except Empty:
        pass  # No results yet

# Name of the trigger CHOP (create a Constant CHOP with this name)
TRIGGER_CHOP_NAME = "new_image_trigger"

def load_result_file(path):
    """Load result (image or video) into output TOP."""
    out = op(OUTPUT_TOP_NAME)
    if out is None:
        log(f"Output TOP '{OUTPUT_TOP_NAME}' not found!")
        return
    
    log(f"Loading result: {path}")
    
    # Set the new file path (it's a different file now, so TD will reload)
    out.par.file = path
    
    # Check if it's a video or image based on extension
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.mp4', '.mov', '.webm', '.gif', '.avi']:
        # Video: configure playback
        try:
            out.par.playmode = 1    # 1 = Loop
            out.par.speed = 1.0     # Normal speed
            out.par.cuepoint = 0    # Start from beginning
            out.par.play = True     # Make sure it's playing
            log("Video loaded and looping!")
        except:
            pass  # May not be a video-capable TOP
    else:
        # Image: just load it
        log("Image loaded!")
    
    # TRIGGER: Pulse a CHOP to signal new image arrived
    trigger = op(TRIGGER_CHOP_NAME)
    if trigger is not None:
        try:
            # For Trigger CHOP: use triggerpulse parameter
            if hasattr(trigger.par, 'triggerpulse'):
                trigger.par.triggerpulse.pulse()
                log("Pulsed Trigger CHOP!")
            # For Constant CHOP: toggle value
            elif hasattr(trigger.par, 'value0'):
                trigger.par.value0 = 1
                # Reset after a moment using run() 
                run("op('{}').par.value0 = 0".format(TRIGGER_CHOP_NAME), delayFrames=5)
                log("Triggered Constant CHOP (will reset in 5 frames)")
            else:
                log(f"Unknown CHOP type for {TRIGGER_CHOP_NAME}")
        except Exception as e:
            log(f"Trigger error: {e}")
    else:
        log(f"Note: Create a Trigger CHOP named '{TRIGGER_CHOP_NAME}'")

# =============================================================================
# TD CALLBACKS
# =============================================================================

_frame_count = 0
_submit_interval = 30  # Submit new frame every N frames after result

def onStart():
    """Called when Start is pressed."""
    global _frame_count, _is_processing
    _frame_count = 0
    _is_processing = False
    
    log("=== START ===")
    start_worker()
    
    # Submit first frame
    request_frame_processing()

def onFrameStart(frame):
    """Called every frame - must be FAST."""
    global _frame_count
    
    _frame_count += 1
    
    # Always check for results (non-blocking)
    check_for_results()
    
    # If not processing and interval passed, submit new frame
    if not _is_processing and (_frame_count % _submit_interval == 0):
        request_frame_processing()

def onDestroy():
    """Called when DAT is destroyed."""
    stop_worker()

# =============================================================================
# STARTUP
# =============================================================================
log("====================================")
log("ComfyUI Client - THREADED VERSION")
log("All HTTP in background thread")
log(f"Server: {SERVER_URL}")
log(f"Source: {SOURCE_TOP_NAME}")
log(f"Output: {OUTPUT_TOP_NAME}")
log("====================================")
log("Press Start or turn on Frame Start!")

# Auto-start worker
start_worker()