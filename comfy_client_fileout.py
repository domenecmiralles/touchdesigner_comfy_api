"""
ComfyUI Client for TouchDesigner - MOVIE FILE OUT VERSION

Uses a Movie File Out TOP in image sequence mode to save frames.

SETUP:
1. Create your source TOP (Movie File In, Camera, etc.) named "source_top"
2. (Optional) Create a "Movie File Out" TOP named "moviefileout1"
   - Type: Image Sequence
   - Image File Type: PNG
   - File: /tmp/td_frame
3. Create an Execute DAT, paste this script
4. Turn on "Frame Start" in Execute DAT parameters
"""

import os
import urllib.request
import json
import ssl
import tempfile

# Disable SSL verification
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# =============================================================================
# CONFIGURATION - EDIT THESE!
# =============================================================================

SERVER_URL = "https://beach-restructuring-penn-tvs.trycloudflare.com"
MOVIE_FILE_OUT_NAME = "moviefileout1"       # Name of your Movie File Out TOP
SOURCE_TOP_NAME = "source_top"              # Name of your source TOP
OUTPUT_TOP_NAME = "output"                  # Movie File In TOP for results
PROMPT = ""
ACTIVE = True

# Cross-platform temp path
FRAME_PATH = os.path.join(tempfile.gettempdir(), "td_comfy_frame.png")

# =============================================================================
# STATE
# =============================================================================

_job_id = None
_waiting = False
_counter = 0
_result_path = None
_initialized = False

def log(msg):
    print(f"[ComfyClient] {msg}")

# =============================================================================
# HTTP CLIENT
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
    with urllib.request.urlopen(url, timeout=30, context=ssl_context) as resp:
        return json.loads(resp.read())

def http_get_binary(url):
    with urllib.request.urlopen(url, timeout=60, context=ssl_context) as resp:
        return resp.read()

# =============================================================================
# FRAME SAVING
# =============================================================================

def save_frame_to_file():
    """Save current frame to file. Returns file path or None."""
    import time
    import glob
    
    # Method 1: Movie File Out TOP
    mfo = op(MOVIE_FILE_OUT_NAME)
    if mfo is not None:
        try:
            base_path = mfo.par.file.eval()
            log(f"Movie File Out path: {base_path}")
            
            mfo.par.record.pulse()
            time.sleep(0.15)
            
            folder = os.path.dirname(base_path) or "."
            name = os.path.basename(base_path)
            pattern = os.path.join(folder, name + "*")
            files = glob.glob(pattern)
            if files:
                latest = max(files, key=os.path.getmtime)
                if os.path.getsize(latest) > 100:
                    log(f"Using: {latest}")
                    return latest
        except Exception as e:
            log(f"Movie File Out failed: {e}")
    
    # Method 2: Direct TOP.save()
    source = op(SOURCE_TOP_NAME)
    if source is not None:
        try:
            log(f"Saving {source.path} to {FRAME_PATH}")
            source.save(FRAME_PATH)
            time.sleep(0.1)
            
            if os.path.exists(FRAME_PATH) and os.path.getsize(FRAME_PATH) > 100:
                log(f"Saved: {FRAME_PATH}")
                return FRAME_PATH
        except Exception as e:
            log(f"Direct save failed: {e}")
    
    log("ERROR: Could not save frame!")
    return None

def initialize():
    global _initialized, _result_path
    if _initialized:
        return True
    
    mfo = op(MOVIE_FILE_OUT_NAME)
    source = op(SOURCE_TOP_NAME)
    
    if mfo is None and source is None:
        log(f"ERROR: Need '{MOVIE_FILE_OUT_NAME}' or '{SOURCE_TOP_NAME}'")
        return False
    
    if mfo:
        log(f"Found Movie File Out: {mfo.path}")
    if source:
        log(f"Found Source TOP: {source.path}")
    
    try:
        health = http_get(f"{SERVER_URL}/health")
        log(f"Server: {health.get('status')}")
    except Exception as e:
        log(f"Server error: {e}")
        return False
    
    _result_path = os.path.join(tempfile.gettempdir(), "td_comfy_result.mp4")
    log(f"Result path: {_result_path}")
    
    _initialized = True
    log("Ready!")
    return True

def submit_frame():
    global _job_id, _waiting
    
    file_path = save_frame_to_file()
    if not file_path:
        return False
    
    size = os.path.getsize(file_path)
    
    with open(file_path, 'rb') as f:
        header = f.read(8)
    
    if header.startswith(b'\x89PNG'):
        log(f"PNG: {size} bytes")
    elif header.startswith(b'\xff\xd8'):
        log(f"JPEG: {size} bytes")
    else:
        log(f"Format: {header[:4]!r}, {size} bytes")
    
    try:
        result = http_post_file(f"{SERVER_URL}/jobs", file_path, PROMPT)
        _job_id = result['job_id']
        _waiting = True
        log(f"Submitted: {_job_id}")
        return True
    except Exception as e:
        log(f"Submit error: {e}")
        return False

def check_result():
    global _job_id, _waiting
    
    if not _job_id:
        return
    
    try:
        status = http_get(f"{SERVER_URL}/jobs/{_job_id}")
        job_status = status.get('status')
        
        if job_status == 'done':
            log("Downloading...")
            video = http_get_binary(f"{SERVER_URL}/jobs/{_job_id}/result")
            with open(_result_path, 'wb') as f:
                f.write(video)
            log(f"Saved: {len(video)} bytes")
            
            out = op(OUTPUT_TOP_NAME)
            if out:
                out.par.file = _result_path
                out.par.cuepoint = 0
                out.par.play = True
            
            _job_id = None
            _waiting = False
            log("Done!")
            
        elif job_status == 'error':
            log(f"Failed: {status.get('error_message', '?')}")
            _job_id = None
            _waiting = False
        else:
            log(f"Status: {job_status}")
            
    except Exception as e:
        log(f"Check error: {e}")

def main_loop():
    global _counter
    
    if not ACTIVE:
        return
    if not initialize():
        return
    
    _counter += 1
    if _counter % 15 != 0:
        return
    
    if _waiting:
        check_result()
    else:
        submit_frame()

# =============================================================================
# TD CALLBACKS
# =============================================================================

def onStart():
    global _initialized, _waiting, _job_id
    _initialized = False
    _waiting = False
    _job_id = None
    log("=== START ===")
    initialize()
    submit_frame()

def onFrameStart(frame):
    main_loop()

def onCook(scriptOp):
    main_loop()

# =============================================================================
# STARTUP
# =============================================================================
log("====================================")
log("ComfyUI Client - MOVIE FILE OUT")
log(f"Server: {SERVER_URL}")
log(f"Movie File Out: {MOVIE_FILE_OUT_NAME}")
log(f"Source TOP: {SOURCE_TOP_NAME}")
log(f"Output TOP: {OUTPUT_TOP_NAME}")
log("====================================")
log(f"1. Create source TOP named '{SOURCE_TOP_NAME}'")
log(f"2. (Optional) Movie File Out named '{MOVIE_FILE_OUT_NAME}'")
log("3. Turn on 'Frame Start' in Execute DAT")
