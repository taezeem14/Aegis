import logging
import asyncio
import inspect
from typing import Callable, Optional, Dict, Any, List

from core.actions import ActionType, AgentAction, ActionParseError
from core.browser import BrowserController, ExecutionError
from core.ai_client import SpectrixClient
from core.history import HistoryManager
import core.safety as safety
from config.settings import settings

logger = logging.getLogger(__name__)

class AegisAgent:
    """
    The main agent loop orchestrator for the Aegis autonomous browser agent.
    Ties together browser, AI client, history, and safety into the core autonomous loop.
    """

    def __init__(self) -> None:
        """
        Initializes the agent with its core dependencies.
        """
        self.browser = BrowserController()
        self.ai_client = SpectrixClient()
        self.history = HistoryManager()
        
        self._step_callbacks: List[Callable] = []
        self._confirmation_handler: Optional[Callable] = None

    def add_step_callback(self, callback: Callable) -> None:
        """
        Registers a callback function to receive step updates.
        Callbacks can be synchronous or asynchronous.
        
        Args:
            callback: The callable to be invoked on step updates.
        """
        self._step_callbacks.append(callback)

    def set_confirmation_handler(self, handler: Callable) -> None:
        """
        Sets the asynchronous handler for confirming destructive actions.
        
        Args:
            handler: An async callable taking (session_id, action, confirm_msg) returning bool.
        """
        self._confirmation_handler = handler

    async def emit_step_update(
        self,
        session_id: str,
        step_number: int,
        message: str,
        status: str,
        action: Optional[AgentAction] = None,
        screenshot: Optional[str] = None
    ) -> None:
        """
        Calls all registered step callbacks with structured data about the current step.
        
        Args:
            session_id: The current task session ID.
            step_number: The current step counter.
            message: Informational message about the step.
            status: The status of the step (e.g., 'deciding', 'error', 'executed').
            action: The AgentAction instance, if any.
            screenshot: Base64 encoded screenshot string, if any.
        """
        update_data = {
            "session_id": session_id,
            "step_number": step_number,
            "message": message,
            "status": status,
            "action": action.model_dump() if action else None,
            "screenshot": screenshot
        }

        for callback in self._step_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    await callback(update_data)
                else:
                    callback(update_data)
            except Exception as e:
                logger.error(f"Error in step callback: {e}")

    async def run_task(
        self,
        task: str,
        headless: Optional[bool] = None,
        max_steps: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        The core autonomous loop for executing a requested task.
        
        Args:
            task: The natural language description of the task to perform.
            headless: Whether to run the browser in headless mode. Defaults to settings.
            max_steps: The maximum number of actions to take. Defaults to settings.
            
        Returns:
            A dictionary containing the session summary.
        """
        if headless is None:
            headless = getattr(settings, "HEADLESS_DEFAULT", True)
        if max_steps is None:
            max_steps = getattr(settings, "MAX_STEPS_DEFAULT", 50)

        await self.history.init_db()
        await self.browser.launch(headless)
        
        async def on_screencast_frame(frame_base64):
            await self._emit_step_update({
                "session_id": session_id,
                "type": "live_frame",
                "status": "screencast",
                "screenshot": frame_base64
            })

        await self.browser.start_screencast(on_screencast_frame)
        
        step_count = 0
        consecutive_same_action = 0
        consecutive_errors = 0
        last_action_signature = None
        urls_without_change = 0
        last_url = None

        try:
            while step_count < max_steps:
                step_count += 1
                logger.info(f"Starting step {step_count} for session {session_id}")

                # 1. Capture state
                screenshot = await self.browser.capture_screenshot()
                dom_summary = await self.browser.extract_condensed_dom()
                current_url = self.browser.get_current_url()

                # 2. Build context
                recent_actions = await self.history.get_recent_actions(session_id, limit=5)
                formatted_actions = []
                for a in recent_actions:
                    formatted_actions.append(f"Step {a.get('step_number')}: {a.get('action_type')} -> {a.get('result')}")
                
                context = {
                    "task": task,
                    "current_url": current_url,
                    "dom_summary": dom_summary,
                    "step_number": step_count,
                    "max_steps": max_steps,
                    "recent_actions": formatted_actions
                }

                # 3. Get next action from AI
                try:
                    action = await self.ai_client.get_next_action(context, screenshot)
                except Exception as e:
                    logger.error(f"AI error at step {step_count}: {e}")
                    await self.emit_step_update(session_id, step_count, f"AI error: {e}", "error")
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        await self.emit_step_update(session_id, step_count, "3 consecutive AI errors, aborting", "aborted")
                        await self.history.update_session_status(session_id, "failed")
                        break
                    continue

                # 4. Emit reasoning
                await self.emit_step_update(session_id, step_count, action.reasoning, "deciding", action=action, screenshot=screenshot)

                # 5. Check terminal states
                if action.action == ActionType.complete:
                    await self.history.log_action(session_id, step_count, action, "success")
                    await self.history.update_session_status(session_id, "completed")
                    msg = action.value or "Task completed"
                    await self.emit_step_update(session_id, step_count, msg, "complete", action=action, screenshot=screenshot)
                    break

                if action.action == ActionType.abort:
                    await self.history.log_action(session_id, step_count, action, "aborted")
                    await self.history.update_session_status(session_id, "aborted")
                    msg = action.value or "Task aborted"
                    await self.emit_step_update(session_id, step_count, msg, "aborted", action=action, screenshot=screenshot)
                    break

                # 6. Safety check
                is_destructive = safety.classify(action, dom_summary)
                if is_destructive:
                    confirm_msg = safety.format_confirmation_message(action, current_url)
                    await self.emit_step_update(
                        session_id, step_count, confirm_msg, "awaiting_confirmation",
                        action=action, screenshot=screenshot
                    )
                    
                    confirmed = False
                    if self._confirmation_handler:
                        try:
                            confirmed = await self._confirmation_handler(session_id, action, confirm_msg)
                        except Exception as e:
                            logger.error(f"Error in confirmation handler: {e}")
                            confirmed = False
                    
                    if not confirmed:
                        await self.history.log_action(session_id, step_count, action, "user_rejected")
                        await self.history.update_session_status(session_id, "stopped")
                        await self.emit_step_update(session_id, step_count, "Action rejected by user, aborting task", "aborted", screenshot=screenshot)
                        break

                # 7. Loop detection
                action_signature = f"{action.action.value}:{action.target}"
                if action_signature == last_action_signature:
                    consecutive_same_action += 1
                else:
                    consecutive_same_action = 0
                    last_action_signature = action_signature

                if consecutive_same_action >= 3:
                    await self.history.log_action(session_id, step_count, action, "loop_detected")
                    await self.history.update_session_status(session_id, "failed")
                    await self.emit_step_update(
                        session_id, step_count,
                        "Aegis appears stuck repeating the same action. Stopping to avoid a loop.",
                        "aborted",
                        screenshot=screenshot
                    )
                    break

                # URL change tracking
                if current_url == last_url:
                    if action.action not in (ActionType.extract, ActionType.screenshot, ActionType.wait):
                        urls_without_change += 1
                    if urls_without_change >= 5:
                        await self.history.update_session_status(session_id, "failed")
                        await self.emit_step_update(
                            session_id, step_count,
                            "Page URL unchanged for 5 consecutive action steps. Possible stuck state, aborting.",
                            "aborted",
                            screenshot=screenshot
                        )
                        break
                else:
                    urls_without_change = 0
                
                last_url = current_url

                # 8. Execute action
                try:
                    result = await self.browser.execute_action(action)
                    post_screenshot = None
                    try:
                        post_screenshot = await self.browser.capture_screenshot()
                    except Exception:
                        post_screenshot = screenshot
                    await self.history.log_action(session_id, step_count, action, "success", data=result)
                    await self.emit_step_update(session_id, step_count, f"Executed: {action.action.value}", "executed", action=action, screenshot=post_screenshot)
                    consecutive_errors = 0
                except ExecutionError as e:
                    logger.error(f"Execution error at step {step_count}: {e}")
                    await self.history.log_action(session_id, step_count, action, "error", data=str(e))
                    await self.emit_step_update(session_id, step_count, f"Action failed: {e}", "error")
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        await self.history.update_session_status(session_id, "failed")
                        await self.emit_step_update(session_id, step_count, "3 consecutive execution errors, aborting.", "aborted")
                        break

            else:
                # while loop exhausted (max_steps reached)
                await self.history.update_session_status(session_id, "timeout")
                await self.emit_step_update(session_id, step_count, "Max steps reached without completion", "timeout")

        finally:
            await self.browser.close()

        return await self.history.get_session_summary(session_id)
