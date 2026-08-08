import os
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "D:\\playwright-browsers"

import json
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from web.backend.routes import router, active_connections, pending_confirmations, confirmation_responses

app = FastAPI(title="Aegis - Autonomous Browser Agent")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = Path(__file__).parent.parent / "frontend"

# Mount static files
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/", response_class=FileResponse)
async def get_index():
    """
    Serve the frontend index.html
    """
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>Aegis Frontend (index.html not found)</h1>")

app.include_router(router)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for step updates and confirmation prompts.
    """
    await websocket.accept()
    active_connections[session_id] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "confirmation_response":
                    confirmed = msg.get("data", {}).get("confirmed", False)
                    confirmation_responses[session_id] = confirmed
                    
                    # Notify the pending confirmation handler
                    event = pending_confirmations.get(session_id)
                    if event:
                        event.set()
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        if session_id in active_connections:
            del active_connections[session_id]
