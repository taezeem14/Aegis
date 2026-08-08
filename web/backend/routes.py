import asyncio
import uuid
from typing import Dict, Any, Optional
from fastapi import APIRouter, WebSocket, BackgroundTasks, HTTPException
from pydantic import BaseModel
from core.agent import AegisAgent
from core.history import HistoryManager

router = APIRouter()

# Global state for WebSockets shared with app.py
active_connections: Dict[str, WebSocket] = {}
pending_confirmations: Dict[str, asyncio.Event] = {}
confirmation_responses: Dict[str, bool] = {}

class TaskRequest(BaseModel):
    task: str
    headless: bool = True
    max_steps: int = 25

history_manager = HistoryManager()

@router.post("/api/task")
async def create_task(request: TaskRequest, background_tasks: BackgroundTasks):
    """
    Creates a new task and runs it in the background.
    """
    session_id = str(uuid.uuid4())
    agent = AegisAgent()
    
    async def step_callback(step_data: dict):
        """Send step updates to the connected client."""
        if session_id in active_connections:
            ws = active_connections[session_id]
            try:
                await ws.send_json({
                    "type": "step_update",
                    "data": step_data
                })
            except Exception:
                pass
                
    async def confirmation_handler(sess_id: str, action: str, confirm_msg: str) -> bool:
        """Handle required confirmations by prompting the client via WebSocket."""
        if sess_id not in active_connections:
            return False
            
        ws = active_connections[sess_id]
        event = asyncio.Event()
        pending_confirmations[sess_id] = event
        
        try:
            await ws.send_json({
                "type": "confirmation_needed",
                "data": {
                    "session_id": sess_id,
                    "message": confirm_msg,
                    "action": action,
                    "screenshot": None
                }
            })
        except Exception:
            return False
            
        await event.wait()
        response = confirmation_responses.get(sess_id, False)
        
        # Cleanup
        pending_confirmations.pop(sess_id, None)
        confirmation_responses.pop(sess_id, None)
            
        return response

    agent.add_step_callback(step_callback)
    agent.set_confirmation_handler(confirmation_handler)
    
    async def run_agent():
        """Run the agent task in the background and notify completion."""
        # Short pause to ensure WebSocket connection is established from frontend
        await asyncio.sleep(0.5)
        try:
            summary = await agent.run_task(
                task=request.task, 
                headless=request.headless, 
                max_steps=request.max_steps
            )
            if session_id in active_connections:
                ws = active_connections[session_id]
                try:
                    await ws.send_json({
                        "type": "task_complete",
                        "data": {"summary": summary}
                    })
                except Exception:
                    pass
        except Exception as e:
            if session_id in active_connections:
                ws = active_connections[session_id]
                try:
                    await ws.send_json({
                        "type": "task_complete",
                        "data": {"summary": {"error": str(e)}}
                    })
                except Exception:
                    pass

    background_tasks.add_task(run_agent)
    
    return {"session_id": session_id, "status": "started"}

@router.get("/api/history")
async def get_history():
    """Returns list of all sessions."""
    sessions = await history_manager.list_sessions()
    return sessions

@router.get("/api/history/{session_id}")
async def get_session_history(session_id: str):
    """Returns session summary and all actions for a given session."""
    try:
        summary = await history_manager.get_session_summary(session_id)
        actions = await history_manager.get_session_actions(session_id)
        return {
            "summary": summary,
            "actions": actions
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail="Session not found")
