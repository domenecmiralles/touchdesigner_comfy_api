"""
ComfyUI Client Component for TouchDesigner

A self-contained component that sends frames to ComfyUI and receives video results.
All settings are configurable via the component's custom parameters in the UI.

SETUP INSTRUCTIONS:
===================

1. In TouchDesigner, create a new Base COMP (right-click → Component → Base)

2. Rename it to "comfy_client" (or any name you prefer)

3. Right-click the Base → Customize Component → Add custom parameters:
   
   Page: "Comfy" (create new page)
   
   | Name         | Type    | Default Value                                          |
   |--------------|---------|--------------------------------------------------------|
   | Serverurl    | String  | https://beach-restructuring-penn-tvs.trycloudflare.com |
   | Prompt       | String  | (empty)                                                |
   | Sourcetop    | TOP     | (drag-drop your input TOP here)                        |
   | Pollinterval | Int     | 15                                                     |
   | Active       | Toggle  | Off                                                    |
   
   Page: "Status" (create new page)  
   
   | Name         | Type    | Default Value |
   |--------------|---------|---------------|
   | Jobid        | String  | (empty)       |
   | Jobstatus    | String  | idle          |
   | Lastresult   | String  | (empty)       |

4. Inside the Base COMP, create:
   - A Text DAT named "script" - paste this entire script into it
   - An Execute DAT named "execute" - set its DAT parameter to "script"
   - A Movie File In TOP named "output" - this will show the result video

5. Set the Execute DAT's "Run" parameter to ON

6. You can now:
   - Set the Server URL in the component parameters
   - Choose your input TOP in the Sourcetop parameter
   - Type a prompt if desired
   - Toggle Active to start the automatic loop

7. Save as .tox: Right-click the Base COMP → Save Component .tox
   Then share this .tox file - anyone can drag-drop it into their project!

================================================================================
"""

import os
import urllib.request
import urllib.parse
import json
import tempfile
import time

# =============================================================================
# STATE (global within this component)
# =============================================================================

_client = None
_current_job_id = None
_waiting_for_result = False
_frame_counter = 0
_temp_video_path = None
_initialized = False
_last_error = None

# =============================================================================
# PARAMETER HELPERS
# =============================================================================

def get_comp():
    """Get the parent component (Base COMP)."""
    return parent()

def get_param(name, default=None):
    """Get a custom parameter value."""
    try:
        comp = get_comp()
        if hasattr(comp.par, name):
            return getattr(comp.par, name).eval()
        return default
    except:
        return default

def set_param(name, value):
    """Set a custom parameter value."""
    try:
        comp = get_comp()
        if hasattr(comp.par, name):
            getattr(comp.par, name).val = value
    except:
        pass

def get_source_top():
    """Get the source TOP from parameter."""
    try:
        comp = get_comp()
        if hasattr(comp.par, 'Sourcetop'):
            return comp.par.Sourcetop.eval()
        return None
    except:
        return None

def get_output_top():
    """Get the output Movie File In TOP inside this component."""
    try:
        return op('output')
    except:
        return None

def log(msg):
    """Log message and update status."""
    print(f"[ComfyClient] {msg}")

def update_status(status):
    """Update the status parameter."""
    set_param('Jobstatus', status)

# =============================================================================
# HTTP CLIENT
# =============================================================================

class ComfyClient:
    """HTTP client for ComfyUI API."""
    
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
        """Delete job."""
        url = f"{self.server_url}/jobs/{job_id}"
        req = urllib.request.Request(url, method='DELETE')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout):
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
# MAIN LOGIC
# =============================================================================

def initialize():
    """Initialize the client."""
    global _client, _temp_video_path, _initialized
    
    if _initialized:
        return True
    
    server_url = get_param('Serverurl', '')
    if not server_url:
        log("ERROR: Server URL is empty!")
        update_status("error: no url")
        return False
    
    try:
        _client = ComfyClient(server_url)
        
        # Set up temp video path
        _temp_video_path = os.path.join(tempfile.gettempdir(), "td_comfy_result.mp4")
        
        # Test connection
        health = _client.health_check()
        if health.get('status') == 'healthy':
            log(f"Connected to: {server_url}")
            update_status("connected")
        else:
            log(f"Warning: Server returned: {health}")
            update_status("warning: check server")
        
        _initialized = True
        return True
        
    except Exception as e:
        log(f"Init error: {e}")
        update_status(f"error: {e}")
        return False


def reset():
    """Reset the client state."""
    global _client, _initialized, _current_job_id, _waiting_for_result
    _client = None
    _initialized = False
    _current_job_id = None
    _waiting_for_result = False
    update_status("idle")
    set_param('Jobid', '')


def capture_and_send():
    """Capture frame and send to API."""
    global _current_job_id, _waiting_for_result
    
    source = get_source_top()
    if source is None:
        log("ERROR: No source TOP selected!")
        update_status("error: no source")
        return False
    
    prompt = get_param('Prompt', '')
    
    try:
        # Capture frame
        image_bytes = top_to_png_bytes(source)
        log(f"Captured: {len(image_bytes)} bytes")
        update_status("sending...")
        
        # Submit
        _current_job_id = _client.submit_frame(image_bytes, prompt=prompt)
        _waiting_for_result = True
        
        set_param('Jobid', _current_job_id)
        log(f"Submitted job: {_current_job_id}")
        update_status(f"processing: {_current_job_id}")
        
        return True
        
    except Exception as e:
        log(f"Send error: {e}")
        update_status(f"error: {e}")
        _waiting_for_result = False
        return False


def check_result():
    """Check job status and handle completion."""
    global _current_job_id, _waiting_for_result
    
    if not _current_job_id:
        return
    
    try:
        status = _client.check_job(_current_job_id)
        job_status = status.get('status', 'unknown')
        
        if job_status == 'done':
            log(f"Job complete, downloading...")
            update_status("downloading...")
            
            # Download result
            video_bytes = _client.get_result(_current_job_id)
            
            # Save to temp file
            with open(_temp_video_path, 'wb') as f:
                f.write(video_bytes)
            log(f"Saved: {len(video_bytes)} bytes")
            
            # Update output TOP
            output = get_output_top()
            if output:
                output.par.file = _temp_video_path
                output.par.cuepoint = 0
                output.par.play = True
            
            set_param('Lastresult', _temp_video_path)
            
            # Cleanup
            _client.delete_job(_current_job_id)
            
            # Reset for next frame
            _current_job_id = None
            _waiting_for_result = False
            set_param('Jobid', '')
            update_status("done - ready")
            
        elif job_status == 'error':
            error_msg = status.get('error_message', 'Unknown')
            log(f"Job failed: {error_msg}")
            update_status(f"error: {error_msg}")
            _current_job_id = None
            _waiting_for_result = False
            set_param('Jobid', '')
            
        elif job_status == 'running':
            update_status(f"running: {_current_job_id}")
            
        elif job_status == 'queued':
            update_status(f"queued: {_current_job_id}")
            
    except Exception as e:
        log(f"Check error: {e}")


# =============================================================================
# TOUCHDESIGNER CALLBACKS
# =============================================================================

def onSetupParameters(scriptOp):
    """Called on setup - not used here since params are on parent."""
    pass


def onCook(scriptOp):
    """Called every frame."""
    global _frame_counter, _initialized
    
    # Check if Active
    active = get_param('Active', False)
    if not active:
        if _initialized:
            reset()
        return
    
    # Initialize if needed
    if not initialize():
        return
    
    _frame_counter += 1
    poll_interval = get_param('Pollinterval', 15)
    
    if _waiting_for_result:
        # Poll for result
        if _frame_counter % poll_interval == 0:
            check_result()
    else:
        # Ready to send new frame
        capture_and_send()


def onPulse(par):
    """Called when a pulse parameter is triggered."""
    if par.name == 'Testconnection':
        if _client:
            health = _client.health_check()
            log(f"Health: {health}")
            update_status(f"health: {health.get('status', 'unknown')}")
    elif par.name == 'Reset':
        reset()
        log("Reset complete")


# =============================================================================
# For testing outside TD
# =============================================================================

if __name__ == "__main__":
    print("This script runs inside TouchDesigner as part of a Base COMP.")
    print("See the setup instructions at the top of this file.")