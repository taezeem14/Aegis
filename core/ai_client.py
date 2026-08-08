import json
import logging
from typing import Any, Dict, List, Optional
import aiohttp

from core.actions import ActionParseError, AgentAction, parse_and_validate
from config.settings import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Aegis, an autonomous browser agent. You observe a web page's current state and decide the next action to take toward completing a user's task.

You must output your decision in the EXACT JSON schema below:
{
  "reasoning": "A brief explanation of why you chose this action",
  "action": "navigate|click|type|scroll|extract|screenshot|wait|complete|abort",
  "target": "CSS selector or URL or null",
  "value": "text or null",
  "is_destructive": false,
  "task_complete": false
}

Action types and usage:
- navigate: Go to a new URL. Set "target" to the URL.
- click: Click on an element. Set "target" to the CSS selector.
- type: Type text into an element. Set "target" to the CSS selector and "value" to the text.
- scroll: Scroll the page. Set "value" to "up" or "down".
- extract: Extract text from an element or page. Set "target" to the CSS selector.
- screenshot: Take a screenshot of the page.
- wait: Wait for elements to load or animations to finish. Set "value" to the number of milliseconds.
- complete: Mark the task as complete. Use this when you have concrete evidence the task is done (visible confirmation text, extracted data matching what was asked, etc), not just because you performed an action that seemed related. Set "task_complete" to true.
- abort: Abort the task. If the page shows a CAPTCHA, login wall you cannot bypass, or paywall, use the abort action and explain why in value. Do not attempt to guess passwords or bypass security measures. Set "target" to null.

Use the condensed DOM selectors provided in the context for targeting elements.

Return ONLY valid JSON. No markdown fences, no preamble, no explanation outside the JSON object. Only mark task_complete: true and use the complete action when you have concrete evidence the task is done.
"""

class SpectrixClient:
    """Client for the Spectrix Worker AI endpoint to get next actions."""
    
    def __init__(self):
        self.base_url = settings.SPECTRIX_WORKER_URL.rstrip('/')
        self.model = settings.AI_MODEL
        self.fallback_model = settings.FALLBACK_AI_MODEL

    async def _make_request(self, session: aiohttp.ClientSession, messages: List[Dict[str, Any]], model_override: Optional[str] = None) -> str:
        """Helper to make the API request and extract the content."""
        target_model = model_override or self.model
        payload = {
            "model": target_model,
            "messages": messages
        }
        
        url = f"{self.base_url}/chat"
        logger.debug(f"Sending request to {url} with model {target_model}")
        
        headers = {
            "Content-Type": "application/json",
            "Origin": "https://spectrix-ai.vercel.app",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        async with session.post(url, json=payload, headers=headers) as response:
            if not response.ok:
                err_text = await response.text()
                logger.error(f"Spectrix API Error [{response.status}]: {err_text}")
                raise Exception(f"Spectrix API Error [{response.status}]: {err_text}")
            data = await response.json()
            return data["choices"][0]["message"]["content"]

    def _format_user_message(self, context: dict, screenshot_base64: Optional[str] = None) -> Dict[str, Any]:
        """Format the user message based on context and screenshot."""
        
        task = context.get("task", "Unknown task")
        url = context.get("current_url", "Unknown URL")
        step = context.get("step_number", 1)
        max_steps = context.get("max_steps", "?")
        dom_summary = context.get("dom_summary", "No DOM elements")
        history = context.get("recent_actions", [])
        
        history_str = "\n".join([f"- {a}" for a in history]) if history else "None"
        
        text_content = f"""TASK: {task}
CURRENT URL: {url}
STEP: {step}/{max_steps}

PAGE ELEMENTS:
{dom_summary}

RECENT ACTIONS:
{history_str}

Decide the next action."""

        if screenshot_base64:
            return {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_content},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_base64}"
                        }
                    }
                ]
            }
        else:
            return {
                "role": "user",
                "content": text_content
            }

    async def get_next_action(self, context: dict, screenshot_base64: Optional[str] = None) -> AgentAction:
        """
        Get the next action from the AI based on the current context.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            self._format_user_message(context, screenshot_base64)
        ]
        
        async with aiohttp.ClientSession() as session:
            try:
                try:
                    content = await self._make_request(session, messages)
                except Exception as req_err:
                    logger.warning(f"Primary model request ({self.model}) failed: {req_err}. Retrying with fallback model {self.fallback_model}.")
                    messages[1] = self._format_user_message(context, screenshot_base64=None)
                    content = await self._make_request(session, messages, model_override=self.fallback_model)

                try:
                    return parse_and_validate(content)
                except ActionParseError:
                    logger.warning("Failed to parse AI response. Retrying with a corrective message.")
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": "Your last response was not valid JSON. Return ONLY the JSON object with the schema: {\"reasoning\": \"...\", \"action\": \"...\", \"target\": \"...\", \"value\": \"...\", \"is_destructive\": false, \"task_complete\": false}"
                    })
                    
                    content = await self._make_request(session, messages)
                    return parse_and_validate(content)
                    
            except Exception as e:
                logger.error(f"Error getting next action: {e}")
                raise
