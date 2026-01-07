# TouchDesigner → ComfyUI API Pipeline

An asynchronous pipeline for sending frames from TouchDesigner to ComfyUI for AI processing (image-to-video generation) and receiving results back.

## Architecture

```
┌─────────────────────┐     HTTP POST/GET      ┌─────────────────────┐
│   TouchDesigner     │◄─────────────────────►│     API Server      │
│  (Your TD Machine)  │                        │   (Job Broker)      │
└─────────────────────┘                        └──────────┬──────────┘
                                                          │
                                                          │ Internal
                                                          │
                                               ┌──────────▼──────────┐
                                               │   Worker Process    │
                                               │  (Polls for jobs)   │
                                               └──────────┬──────────┘
                                                          │
                                                          │ ComfyUI API
                                                          │
                                               ┌──────────▼──────────┐
                                               │      ComfyUI        │
                                               │  (localhost:8999)   │
                                               └─────────────────────┘
```

**Flow:**
1. TouchDesigner captures a frame and sends it to the API
2. API queues the job and returns a job ID
3. Worker picks up the job and submits to ComfyUI
4. ComfyUI processes the workflow (LTXV image-to-video)
5. Worker reports completion back to API
6. TouchDesigner polls for status, downloads result when ready
7. TouchDesigner only sends next frame after previous job completes

## Quick Start

### 1. On the ComfyUI Machine (Remote Server)

```bash
# Navigate to the folder
cd /path/to/touchdesigner_comfy_api

# Install dependencies
pip install -r requirements.txt

# Make sure ComfyUI is running
# (In another terminal)
cd ../ComfyUI
python main.py --port 8999

# Start the API server (Terminal 1)
python api_server.py

# Start the worker (Terminal 2)
python worker.py
```

### 2. On the TouchDesigner Machine

Copy `touchdesigner_client.py` to your TD project and use it in an Execute DAT:

```python
import sys
sys.path.insert(0, "/path/to/touchdesigner_comfy_api")

from touchdesigner_client import TDComfyClient, top_to_png_bytes

# Initialize
client = TDComfyClient("http://YOUR_SERVER_IP:8080")

# Submit a frame
image_bytes = top_to_png_bytes(op('your_top'))
job_id = client.submit_frame(image_bytes, prompt="your prompt here")

# Check status (poll periodically)
status = client.check_job(job_id)

# Get result when done
if status['status'] == 'done':
    video_bytes = client.get_result(job_id)
```

## Files

| File | Description |
|------|-------------|
| `api_server.py` | FastAPI server - job broker that handles submissions and results |
| `worker.py` | Worker process that polls API and submits jobs to ComfyUI |
| `touchdesigner_client.py` | Client library for TouchDesigner |
| `config.py` | Configuration settings |
| `requirements.txt` | Python dependencies |
| `workflows/ltxv_image_to_video.json` | ComfyUI workflow template |

## API Endpoints

### Submit Job
```
POST /jobs
Content-Type: multipart/form-data

Fields:
- image: (file) Input image
- prompt: (string, optional) Positive prompt
- negative_prompt: (string, optional) Negative prompt
- seed: (integer, optional) Random seed

Response:
{
  "job_id": "abc12345",
  "status": "queued",
  "message": "Job queued for processing"
}
```

### Get Job Status
```
GET /jobs/{job_id}

Response:
{
  "id": "abc12345",
  "status": "queued|running|done|error",
  "created_at": 1234567890.0,
  "prompt": "your prompt",
  "has_result": false,
  "error_message": null,
  "processing_time": null
}
```

### Download Result
```
GET /jobs/{job_id}/result

Response: Video file (video/mp4)
```

### Delete Job
```
DELETE /jobs/{job_id}
```

### List Jobs
```
GET /jobs?status=queued&limit=50
```

### Health Check
```
GET /health

Response:
{
  "status": "healthy",
  "jobs_count": 5,
  "queued": 2,
  "running": 1,
  "done": 2,
  "error": 0
}
```

## Configuration

Environment variables (or edit `config.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `COMFYUI_HOST` | `127.0.0.1` | ComfyUI server host |
| `COMFYUI_PORT` | `8999` | ComfyUI server port |
| `API_HOST` | `0.0.0.0` | API server bind address |
| `API_PORT` | `8080` | API server port |
| `WORKER_POLL_INTERVAL` | `0.5` | How often worker checks for jobs (seconds) |
| `JOB_TIMEOUT` | `600` | Max time for a job to complete (seconds) |

## TouchDesigner Integration

### Complete Example (Execute DAT)

```python
# ============================================================================
# TouchDesigner ComfyUI Integration
# ============================================================================

import os
import sys

# Add path to touchdesigner_client.py
API_PATH = "/path/to/touchdesigner_comfy_api"
if API_PATH not in sys.path:
    sys.path.insert(0, API_PATH)

from touchdesigner_client import TDComfyClient, top_to_png_bytes

# Configuration
SERVER_URL = "http://192.168.1.100:8080"  # Your server IP
SOURCE_TOP = "source_top"  # Input TOP name
RESULT_TOP = "result_video"  # Movie File In TOP for output
TEMP_VIDEO_PATH = "/tmp/td_comfy_result.mp4"
PROMPT = ""  # Your prompt (empty = no prompt)

# State
client = None
current_job = None
waiting = False

def onCook(scriptOp):
    global client, current_job, waiting
    
    # Initialize once
    if client is None:
        client = TDComfyClient(SERVER_URL)
    
    if not waiting:
        # Submit new frame
        if client.is_ready_for_next():
            try:
                source = op(SOURCE_TOP)
                if source is None:
                    return
                
                image_bytes = top_to_png_bytes(source)
                current_job = client.submit_frame(image_bytes, prompt=PROMPT)
                waiting = True
                print(f"Submitted job: {current_job}")
                
            except Exception as e:
                print(f"Submit error: {e}")
    else:
        # Check for result
        try:
            status = client.check_job(current_job)
            
            if status['status'] == 'done':
                # Download and load result
                video_bytes = client.get_result(current_job)
                
                with open(TEMP_VIDEO_PATH, 'wb') as f:
                    f.write(video_bytes)
                
                result_op = op(RESULT_TOP)
                if result_op:
                    result_op.par.file = TEMP_VIDEO_PATH
                    result_op.par.cuepoint = 0
                    result_op.par.play = True
                
                print(f"Loaded result: {current_job}")
                client.delete_job(current_job)
                current_job = None
                waiting = False
                
            elif status['status'] == 'error':
                print(f"Job failed: {status.get('error_message')}")
                current_job = None
                waiting = False
                
        except Exception as e:
            print(f"Status check error: {e}")
```

### Tips for TouchDesigner

1. **Non-blocking**: The client methods are quick HTTP calls. Don't call them every frame - use a Timer CHOP or similar to poll every 0.5-1 second.

2. **Frame capture**: Use `top_to_png_bytes()` to convert any TOP to PNG bytes for sending.

3. **Result playback**: Load results into a Movie File In TOP. Set it to play once the file is written.

4. **Error handling**: Always wrap client calls in try/except - network errors can occur.

5. **Cleanup**: Call `client.delete_job()` after getting results to free server resources.

## Workflow Customization

The default workflow (`ltxv_image_to_video.json`) uses:
- LTXV model for image-to-video generation
- Configurable prompt (positive and negative)
- 97 frames output at 24fps (~4 seconds)
- 256x160 generation resolution, upscaled to 512x320

To use a different workflow:
1. Export your workflow as API format from ComfyUI
2. Save to `workflows/` folder
3. Update `DEFAULT_WORKFLOW` in `config.py`
4. Update `WORKFLOW_NODES` in `config.py` to match your node IDs

## Troubleshooting

### API server not starting
```bash
# Check if port is in use
lsof -i :8080

# Try different port
API_PORT=8081 python api_server.py
```

### Worker can't connect to ComfyUI
```bash
# Verify ComfyUI is running
curl http://127.0.0.1:8999/prompt

# Check ComfyUI logs for errors
```

### Jobs stuck in "queued"
- Make sure worker is running
- Check worker logs for errors
- Verify ComfyUI connection

### TouchDesigner can't connect
- Check firewall settings on server
- Verify server IP and port
- Test with: `curl http://SERVER_IP:8080/health`

### Video result not loading in TD
- Check the temp file path is writable
- Verify Movie File In TOP settings
- Try different video codec in workflow

## Running as Services (Production)

### Using systemd (Linux)

Create `/etc/systemd/system/td-comfy-api.service`:
```ini
[Unit]
Description=TouchDesigner ComfyUI API
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/touchdesigner_comfy_api
ExecStart=/usr/bin/python3 api_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/td-comfy-worker.service`:
```ini
[Unit]
Description=TouchDesigner ComfyUI Worker
After=td-comfy-api.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/touchdesigner_comfy_api
ExecStart=/usr/bin/python3 worker.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable td-comfy-api td-comfy-worker
sudo systemctl start td-comfy-api td-comfy-worker
```

### Using screen/tmux (Quick)

```bash
# Terminal 1
screen -S api
python api_server.py
# Ctrl+A, D to detach

# Terminal 2
screen -S worker
python worker.py
# Ctrl+A, D to detach

# Reattach later
screen -r api
screen -r worker
```

## License

MIT License - Use freely for your projects.