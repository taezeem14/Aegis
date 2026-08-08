"""
Action schema, validation, and defensive parsing module for Aegis.

This module defines the core action schema and provides robust parsing capabilities
to handle potentially malformed responses from the LLM.
"""

import json
import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ValidationError


class ActionType(str, Enum):
    """Enumeration of all possible actions the agent can take."""
    navigate = "navigate"
    click = "click"
    type = "type"
    scroll = "scroll"
    extract = "extract"
    screenshot = "screenshot"
    wait = "wait"
    complete = "complete"
    abort = "abort"


class AgentAction(BaseModel):
    """
    Pydantic model representing an action chosen by the agent.
    
    This is the core contract between the LLM output and the execution engine.
    """
    reasoning: str
    action: ActionType
    target: Optional[str] = None
    value: Optional[str] = None
    is_destructive: bool = False
    task_complete: bool = False


class ActionParseError(Exception):
    """Raised when an LLM response cannot be parsed into a valid AgentAction."""
    pass


def parse_and_validate(raw_response: str) -> AgentAction:
    """
    Parses and validates a raw string response from the LLM into an AgentAction.
    
    This function defensively cleans the input by:
    1. Stripping leading/trailing whitespace.
    2. Stripping markdown code block fences.
    3. Extracting the first JSON-like object by finding the first '{' and last '}'.
    
    Args:
        raw_response: The raw string output from the LLM.
        
    Returns:
        A validated AgentAction instance.
        
    Raises:
        ActionParseError: If the string is not valid JSON or fails schema validation.
    """
    cleaned_response = raw_response.strip()

    # Strip markdown code fences if present (either ```json or just ```)
    # Using regex to remove them, even if there is surrounding text.
    cleaned_response = re.sub(r"```(?:json)?", "", cleaned_response, flags=re.IGNORECASE)
    cleaned_response = re.sub(r"```", "", cleaned_response)
    
    # Strip any prose text before the first '{'
    first_brace = cleaned_response.find('{')
    
    if first_brace == -1:
        raise ActionParseError("No valid JSON object found in response.")
    
    # Use raw_decode to extract only the first JSON object, handling cases
    # where multiple JSON objects are concatenated (e.g., AI outputs two)
    json_substring = cleaned_response[first_brace:]
    decoder = json.JSONDecoder()
    
    try:
        parsed_dict, _ = decoder.raw_decode(json_substring)
    except json.JSONDecodeError as e:
        raise ActionParseError(f"Failed to decode JSON: {e}\nString attempted: {json_substring[:500]}")
        
    try:
        agent_action = AgentAction.model_validate(parsed_dict)
        return agent_action
    except ValidationError as e:
        raise ActionParseError(f"Failed to validate Action schema: {e}")

