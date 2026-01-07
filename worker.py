"""
ComfyUI Worker for TouchDesigner Pipeline.

This worker polls the API server for new jobs, submits them to ComfyUI,
waits for completion, and reports results back to the API.

Usage:
    python worker.py
"""

import json
import time
import random
import urllib.request
import urllib.parse
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from config import (
    COMFYUI_SERVER,
    COMFYUI_OUTPUT_DIR,
    API_HOST,
    API_PORT,
    WORKER_POLL_INTERVAL,
    COMFYUI_POLL_INTERVAL,
    JOB_TIMEOUT,
    WORKFLOWS_DIR,
    DEFAULT_WORKFLOW,
    WORKFLOW_NODES,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ComfyUIClient:
    """Client for interacting with ComfyUI's API."""
    
    def __init__(self, server_address: str = COMFYUI_SERVER):
        """Initialize the ComfyUI client."""
        self.server_address = server_address
        self.client_id = str(uuid.uuid4())
    
    def queue_prompt(self, prompt: Dict[str, Any]) -> str:
        """Queue a workflow prompt for execution."""
        data = json.dumps({"prompt": prompt, "client_id": self.client_id}).encode('utf-8')
        req = urllib.request.Request(
            f"http://{self.server_address}/prompt",
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read())
            return result['prompt_id']
    
    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        """Get the execution history for a prompt."""
        url = f"http://{self.server_address}/history/{prompt_id}"
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read())
    
    def get_queue(self) -> Dict[str, Any]:
        """Get the current queue status."""
        url = f"http://{self.server_address}/prompt"
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read())
    
    def wait_for_completion(
        self, 
        prompt_id: str, 
        poll_interval: float = COMFYUI_POLL_INTERVAL,
        timeout: Optional[float] = JOB_TIMEOUT
    ) -> Dict[str, Any]:
        """Wait for a prompt to complete execution."""
        start_time = time.time()
        
        while True:
            history = self.get_history(prompt_id)
            
            if prompt_id in history:
                entry = history[prompt_id]
                
                # Check if completed
                if 'outputs' in entry:
                    # Check for errors
                    if entry.get('status', {}).get('status_str') == 'error':
                        error_msg = entry.get('status', {}).get('messages', ['Unknown error'])
                        raise RuntimeError(f"Workflow execution failed: {error_msg}")
                    
                    logger.info(f"Prompt {prompt_id} completed successfully")
                    return entry
            
            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(f"Prompt {prompt_id} did not complete within {timeout}s")
            
            time.sleep(poll_interval)
    
    def get_output_files(
        self, 
        history_entry: Dict[str, Any],
        comfyui_output_dir: Path = COMFYUI_OUTPUT_DIR
    ) -> List[Tuple[str, Path]]:
        """Get output files (images or videos) from a completed workflow."""
        outputs = history_entry.get('outputs', {})
        results = []
        
        for node_id, node_output in outputs.items():
            # Check for image outputs (SaveImage node)
            if 'images' in node_output:
                for image_data in node_output['images']:
                    filename = image_data['filename']
                    subfolder = image_data.get('subfolder', '')
                    
                    if subfolder:
                        file_path = comfyui_output_dir / subfolder / filename
                    else:
                        file_path = comfyui_output_dir / filename
                    
                    if file_path.exists():
                        results.append((node_id, file_path))
                        logger.info(f"Found image output: {file_path}")
                    else:
                        logger.warning(f"Image not found: {file_path}")
            
            # Check for video outputs (SaveVideo node)
            if 'videos' in node_output:
                for video_data in node_output['videos']:
                    filename = video_data['filename']
                    subfolder = video_data.get('subfolder', '')
                    
                    if subfolder:
                        file_path = comfyui_output_dir / subfolder / filename
                    else:
                        file_path = comfyui_output_dir / filename
                    
                    if file_path.exists():
                        results.append((node_id, file_path))
                        logger.info(f"Found video output: {file_path}")
                    else:
                        logger.warning(f"Video not found: {file_path}")
            
            # VHS_VideoCombine outputs gifs
            if 'gifs' in node_output:
                for video_data in node_output['gifs']:
                    filename = video_data['filename']
                    subfolder = video_data.get('subfolder', '')
                    
                    if subfolder:
                        file_path = comfyui_output_dir / subfolder / filename
                    else:
                        file_path = comfyui_output_dir / filename
                    
                    if file_path.exists():
                        results.append((node_id, file_path))
                        logger.info(f"Found video/gif output: {file_path}")
        
        return results


class APIClient:
    """Client for interacting with the job broker API."""
    
    def __init__(self, host: str = API_HOST, port: int = API_PORT):
        """Initialize the API client."""
        # Handle 0.0.0.0 by connecting to localhost
        if host == "0.0.0.0":
            host = "127.0.0.1"
        self.base_url = f"http://{host}:{port}"
    
    def get_next_job(self) -> Optional[Dict[str, Any]]:
        """Get the next queued job."""
        try:
            url = f"{self.base_url}/queue/next"
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read())
                if data.get('job_id'):
                    return data
                return None
        except Exception as e:
            logger.error(f"Error getting next job: {e}")
            return None
    
    def mark_started(self, job_id: str) -> bool:
        """Mark a job as started."""
        try:
            url = f"{self.base_url}/jobs/{job_id}/start"
            req = urllib.request.Request(url, method='POST')
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error marking job started: {e}")
            return False
    
    def mark_complete(self, job_id: str, result_path: str) -> bool:
        """Mark a job as complete with result path."""
        try:
            url = f"{self.base_url}/jobs/{job_id}/complete"
            data = urllib.parse.urlencode({'result_path': result_path}).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error marking job complete: {e}")
            return False
    
    def mark_error(self, job_id: str, error_message: str) -> bool:
        """Mark a job as failed."""
        try:
            url = f"{self.base_url}/jobs/{job_id}/error"
            data = urllib.parse.urlencode({'error_message': error_message}).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error marking job error: {e}")
            return False


def load_workflow(workflow_path: Path) -> Dict[str, Any]:
    """Load a workflow JSON file."""
    with open(workflow_path, 'r') as f:
        return json.load(f)


def inject_value(workflow: Dict[str, Any], node_id: str, field: str, value: Any) -> Dict[str, Any]:
    """Inject a value into a workflow node."""
    if node_id in workflow:
        workflow[node_id]['inputs'][field] = value
    else:
        logger.warning(f"Node {node_id} not found in workflow")
    return workflow


def process_job(
    job: Dict[str, Any],
    comfy_client: ComfyUIClient,
    workflow_path: Path
) -> Path:
    """
    Process a single job through ComfyUI.
    
    Args:
        job: Job data from API
        comfy_client: ComfyUI client instance
        workflow_path: Path to workflow JSON
        
    Returns:
        Path to result file (image or video)
    """
    job_id = job['job_id']
    input_image_path = job['input_image_path']
    prompt = job.get('prompt', '')
    negative_prompt = job.get('negative_prompt')
    seed = job.get('seed')
    
    logger.info(f"Processing job {job_id}")
    logger.info(f"  Input: {input_image_path}")
    logger.info(f"  Prompt: '{prompt[:50]}...' " if len(prompt) > 50 else f"  Prompt: '{prompt}'")
    
    # Load and configure workflow
    workflow = load_workflow(workflow_path)
    
    # Inject input image path (VHS_LoadImagePath node)
    inject_value(workflow, WORKFLOW_NODES['image_input'], 'image', input_image_path)
    
    # Inject positive prompt (only if we have a prompt to inject)
    if prompt:
        inject_value(workflow, WORKFLOW_NODES['positive_prompt'], 'text', prompt)
    
    # Inject negative prompt if provided and node exists
    neg_node = WORKFLOW_NODES.get('negative_prompt')
    if negative_prompt is not None and neg_node is not None:
        inject_value(workflow, neg_node, 'text', negative_prompt)
    
    # Inject seed if provided, otherwise use random
    if seed is None:
        seed = random.randint(1, 2**63)
    # KSampler uses 'seed', SamplerCustom uses 'noise_seed'
    inject_value(workflow, WORKFLOW_NODES['seed'], 'seed', seed)
    
    # Set output filename prefix to include job_id
    output_prefix = f"td_output/{job_id}"
    # Check for image_output or video_output
    output_node = WORKFLOW_NODES.get('image_output') or WORKFLOW_NODES.get('video_output')
    if output_node:
        inject_value(workflow, output_node, 'filename_prefix', output_prefix)
    
    # Queue the workflow
    prompt_id = comfy_client.queue_prompt(workflow)
    logger.info(f"Queued ComfyUI prompt: {prompt_id}")
    
    # Wait for completion
    history = comfy_client.wait_for_completion(prompt_id)
    
    # Get output files (images or videos)
    outputs = comfy_client.get_output_files(history)
    
    if not outputs:
        raise RuntimeError("Workflow completed but no output file found")
    
    # Return the first output
    node_id, output_path = outputs[0]
    logger.info(f"Job {job_id} produced output: {output_path}")
    
    return output_path


def run_worker():
    """Main worker loop."""
    logger.info("=" * 60)
    logger.info("Starting ComfyUI Worker")
    logger.info(f"  API Server: http://{API_HOST}:{API_PORT}")
    logger.info(f"  ComfyUI: http://{COMFYUI_SERVER}")
    logger.info(f"  Poll Interval: {WORKER_POLL_INTERVAL}s")
    logger.info("=" * 60)
    
    # Initialize clients
    api_client = APIClient()
    comfy_client = ComfyUIClient()
    
    # Workflow path
    workflow_path = WORKFLOWS_DIR / DEFAULT_WORKFLOW
    if not workflow_path.exists():
        logger.error(f"Workflow not found: {workflow_path}")
        return
    
    logger.info(f"Using workflow: {workflow_path}")
    
    # Create output directory
    output_dir = COMFYUI_OUTPUT_DIR / "td_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Main loop
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            # Check for next job
            job = api_client.get_next_job()
            
            if job is None:
                # No job available, wait and retry
                time.sleep(WORKER_POLL_INTERVAL)
                consecutive_errors = 0
                continue
            
            job_id = job['job_id']
            logger.info(f"Received job: {job_id}")
            
            # Mark job as started
            if not api_client.mark_started(job_id):
                logger.error(f"Failed to mark job {job_id} as started")
                continue
            
            try:
                # Process the job
                result_path = process_job(job, comfy_client, workflow_path)
                
                # Mark job as complete
                api_client.mark_complete(job_id, str(result_path))
                logger.info(f"Job {job_id} completed successfully")
                
            except Exception as e:
                logger.error(f"Job {job_id} failed: {e}")
                api_client.mark_error(job_id, str(e))
            
            consecutive_errors = 0
            
        except KeyboardInterrupt:
            logger.info("Worker interrupted, shutting down...")
            break
            
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Worker error ({consecutive_errors}/{max_consecutive_errors}): {e}")
            
            if consecutive_errors >= max_consecutive_errors:
                logger.error("Too many consecutive errors, waiting before retry...")
                time.sleep(10)
                consecutive_errors = 0
            else:
                time.sleep(WORKER_POLL_INTERVAL)


def main():
    """Entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="ComfyUI Worker for TouchDesigner Pipeline")
    parser.add_argument("--workflow", type=str, help="Workflow file to use (default: from config)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    run_worker()


if __name__ == "__main__":
    main()