#!/usr/bin/env python3
"""
Mock Gengo Server for Testing

This server simulates the Gengo.com API endpoints needed for testing
job acceptance, cancellation, and WebSocket functionality.
"""

import asyncio
import json
import logging
import random
import time
from typing import Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mock-gengo")

app = FastAPI(title="Mock Gengo Server", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mock data storage
class MockJob(BaseModel):
    id: str
    title: str
    reward: float
    status: str  # "active", "cancelled", "accepted", "expired"
    created_at: float
    accepted_by: Optional[str] = None
    cancelled_at: Optional[float] = None

# Global state
mock_jobs: Dict[str, MockJob] = {}
active_websockets: List[WebSocket] = []
job_counter = 1000

# Test scenarios configuration
SCENARIOS = {
    "normal_flow": {
        "description": "Normal job flow with accept/cancel operations",
        "jobs": [
            {"title": "English > Spanish Translation", "reward": 15.0},
            {"title": "French > English Document", "reward": 25.0},
            {"title": "German > Italian Legal Text", "reward": 45.0},
        ]
    },
    "cancellation_test": {
        "description": "Test job cancellation when better opportunity appears",
        "jobs": [
            {"title": "Basic Translation", "reward": 10.0},
            {"title": "High-Value Contract", "reward": 100.0},  # Should trigger cancellation
        ]
    },
    "server_error": {
        "description": "Simulate server errors during operations",
        "error_rate": 0.3,  # 30% chance of 500 errors
    }
}

current_scenario = "normal_flow"

@app.get("/")
async def root():
    """Root endpoint with server info."""
    return {
        "name": "Mock Gengo Server",
        "version": "1.0.0",
        "scenario": current_scenario,
        "active_jobs": len([j for j in mock_jobs.values() if j.status == "active"]),
        "total_jobs": len(mock_jobs)
    }

@app.post("/api/scenario/{scenario_name}")
async def set_scenario(scenario_name: str):
    """Set the current test scenario."""
    global current_scenario
    if scenario_name not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {scenario_name}")

    current_scenario = scenario_name
    logger.info(f"Switched to scenario: {scenario_name}")

    # Reset job state
    mock_jobs.clear()

    # Initialize jobs for the scenario
    if scenario_name == "normal_flow":
        for i, job_data in enumerate(SCENARIOS[scenario_name]["jobs"]):
            job_id = f"job_{1000 + i}"
            mock_jobs[job_id] = MockJob(
                id=job_id,
                title=job_data["title"],
                reward=job_data["reward"],
                status="active",
                created_at=time.time()
            )

    elif scenario_name == "cancellation_test":
        # Start with one active job
        job_id = "cancel_test_001"
        mock_jobs[job_id] = MockJob(
            id=job_id,
            title=SCENARIOS[scenario_name]["jobs"][0]["title"],
            reward=SCENARIOS[scenario_name]["jobs"][0]["reward"],
            status="active",
            created_at=time.time()
        )

    return {"status": "success", "scenario": scenario_name}

@app.get("/t/jobs/details/{job_id}")
async def get_job_details(job_id: str):
    """Get job details page."""
    if job_id not in mock_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = mock_jobs[job_id]

    # Simulate server errors for error scenario
    if current_scenario == "server_error" and random.random() < SCENARIOS["server_error"]["error_rate"]:
        raise HTTPException(status_code=500, detail="Internal server error")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Job {job_id}</title></head>
    <body>
        <h1>{job.title}</h1>
        <p>Reward: ${job.reward}</p>
        <p>Status: {job.status}</p>
        <p>Created: {datetime.fromtimestamp(job.created_at).strftime('%Y-%m-%d %H:%M:%S')}</p>
        {"<p>Accepted by: " + job.accepted_by + "</p>" if job.accepted_by else ""}
        {"<p>Cancelled at: " + datetime.fromtimestamp(job.cancelled_at).strftime('%Y-%m-%d %H:%M:%S') + "</p>" if job.cancelled_at else ""}
    </body>
    </html>
    """

    return HTMLResponse(content=html_content)

@app.post("/t/jobs/cancel/{job_id}")
async def cancel_job(job_id: str, request: Request):
    """Cancel a job."""
    if job_id not in mock_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = mock_jobs[job_id]

    # Simulate server errors for error scenario
    if current_scenario == "server_error" and random.random() < SCENARIOS["server_error"]["error_rate"]:
        raise HTTPException(status_code=500, detail="Internal server error")

    if job.status != "active":
        raise HTTPException(status_code=400, detail=f"Job is {job.status}, cannot cancel")

    # Mark job as cancelled
    job.status = "cancelled"
    job.cancelled_at = time.time()

    logger.info(f"Job {job_id} cancelled")

    # Broadcast update via WebSocket
    await broadcast_job_update(job)

    return {"status": "success", "message": f"Job {job_id} cancelled"}

@app.post("/t/jobs/accept/{job_id}")
async def accept_job(job_id: str, request: Request):
    """Accept a job."""
    if job_id not in mock_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = mock_jobs[job_id]

    # Simulate server errors for error scenario
    if current_scenario == "server_error" and random.random() < SCENARIOS["server_error"]["error_rate"]:
        raise HTTPException(status_code=500, detail="Internal server error")

    if job.status != "active":
        raise HTTPException(status_code=400, detail=f"Job is {job.status}, cannot accept")

    # Mark job as accepted
    job.status = "accepted"
    job.accepted_by = "test_user"

    logger.info(f"Job {job_id} accepted by test_user")

    # Broadcast update via WebSocket
    await broadcast_job_update(job)

    return {"status": "success", "message": f"Job {job_id} accepted"}

@app.post("/api/jobs/create")
async def create_test_job():
    """Create a new test job."""
    global job_counter
    job_counter += 1
    job_id = f"test_{job_counter}"

    # Create job based on current scenario
    if current_scenario == "cancellation_test" and len(mock_jobs) == 1:
        # Add the high-value job that should trigger cancellation
        job_data = SCENARIOS["cancellation_test"]["jobs"][1]
    else:
        # Create a random job
        rewards = [5.0, 10.0, 15.0, 25.0, 50.0, 100.0]
        titles = [
            "English > Japanese Translation",
            "French > German Document",
            "Spanish > Italian Legal Text",
            "German > English Contract",
            "Chinese > Korean Business Document"
        ]
        job_data = {
            "title": random.choice(titles),
            "reward": random.choice(rewards)
        }

    mock_jobs[job_id] = MockJob(
        id=job_id,
        title=job_data["title"],
        reward=job_data["reward"],
        status="active",
        created_at=time.time()
    )

    logger.info(f"Created test job: {job_id} - {job_data['title']} (${job_data['reward']})")

    # Broadcast new job via WebSocket
    await broadcast_job_update(mock_jobs[job_id])

    return {"status": "success", "job_id": job_id}

@app.get("/api/jobs")
async def list_jobs():
    """List all jobs."""
    return {
        "jobs": [
            {
                "id": job.id,
                "title": job.title,
                "reward": job.reward,
                "status": job.status,
                "created_at": job.created_at,
                "accepted_by": job.accepted_by,
                "cancelled_at": job.cancelled_at
            }
            for job in mock_jobs.values()
        ]
    }

@app.websocket("/ws/jobs")
async def websocket_jobs(websocket: WebSocket):
    """WebSocket endpoint for real-time job updates."""
    await websocket.accept()
    active_websockets.append(websocket)

    try:
        while True:
            # Keep connection alive
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

async def broadcast_job_update(job: MockJob):
    """Broadcast job update to all connected WebSocket clients."""
    message = {
        "type": "job_update",
        "data": {
            "id": job.id,
            "title": job.title,
            "reward": job.reward,
            "status": job.status,
            "created_at": job.created_at,
            "accepted_by": job.accepted_by,
            "cancelled_at": job.cancelled_at
        }
    }

    disconnected = []
    for ws in active_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)

    # Clean up disconnected clients
    for ws in disconnected:
        if ws in active_websockets:
            active_websockets.remove(ws)

@app.on_event("startup")
async def startup_event():
    """Initialize the mock server."""
    logger.info("Mock Gengo Server starting up")
    # Initialize with default scenario
    await set_scenario("normal_flow")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on shutdown."""
    logger.info("Mock Gengo Server shutting down")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mock Gengo Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=3000, help="Port to bind to")
    parser.add_argument("--scenario", default="normal_flow",
                       choices=list(SCENARIOS.keys()),
                       help="Initial test scenario")

    args = parser.parse_args()

    # Set initial scenario
    current_scenario = args.scenario

    print(f"🚀 Starting Mock Gengo Server on http://{args.host}:{args.port}")
    print(f"📋 Current scenario: {current_scenario}")
    print(f"📖 Scenario description: {SCENARIOS[current_scenario]['description']}")
    print("\n📋 Available endpoints:")
    print("  GET  /                          - Server info")
    print("  POST /api/scenario/{name}       - Switch scenario")
    print("  GET  /t/jobs/details/{id}       - Job details page")
    print("  POST /t/jobs/cancel/{id}        - Cancel job")
    print("  POST /t/jobs/accept/{id}        - Accept job")
    print("  POST /api/jobs/create           - Create test job")
    print("  GET  /api/jobs                  - List all jobs")
    print("  WS   /ws/jobs                   - Real-time job updates")
    print("\nPress Ctrl+C to stop")

    uvicorn.run(app, host=args.host, port=args.port)</content>
</xai:function_call"> <parameter name="filePath">scripts/mock_gengo_server.py