"""
Safety module for the Aegis autonomous browser agent.

This module implements a local destructive action classifier that independently
verifies whether a proposed AgentAction is potentially destructive. It does NOT
trust the AI's own `is_destructive` claim. The safety principle is biased toward
false positives: "False positives cost one keypress. False negatives can cost real money or data."
"""

import re
import logging
from core.actions import AgentAction, ActionType
from config.settings import settings

logger = logging.getLogger(__name__)

# Regex matching terms commonly associated with destructive/financial actions
DESTRUCTIVE_PATTERNS = re.compile(
    r"buy|purchase|checkout|pay|confirm.*order|place.*order|submit|delete|remove|"
    r"cancel.*subscription|unsubscribe|send|transfer|withdraw",
    re.IGNORECASE
)

# Regex matching URL paths associated with destructive/financial actions
DESTRUCTIVE_URL_PATTERNS = re.compile(
    r"checkout|payment|confirm",
    re.IGNORECASE
)

# Regex matching fields likely to contain sensitive data
SENSITIVE_FIELD_PATTERNS = re.compile(
    r"password|passwd|credit.?card|card.?number|cvv|cvc|expir|payment|billing",
    re.IGNORECASE
)


def classify(action: AgentAction, dom_summary: str) -> bool:
    """
    Classify whether an action is destructive. This classifier is INDEPENDENT
    of the AI's own is_destructive claim — the AI's flag is never trusted.
    Only this local classifier's verdict matters.

    Safety bias: When in doubt, classify as destructive.
    False positives cost one keypress. False negatives can cost real money or data.

    Args:
        action: The AgentAction proposed by the AI.
        dom_summary: The condensed DOM summary for context about the target element.

    Returns:
        True if the action is classified as destructive, False otherwise.
    """
    if not getattr(settings, "ENABLE_SAFETY_CONFIRMATION", True):
        return False

    action_type = action.action.value  # ActionType enum -> string

    # --- Click actions ---
    if action_type == "click":
        # Check if the target selector itself contains destructive keywords
        if action.target and DESTRUCTIVE_PATTERNS.search(action.target):
            logger.info(f"Safety: destructive pattern matched in click target: {action.target}")
            return True

        # Check if the target element in the DOM summary has destructive text/attributes
        if action.target:
            # Find the line in DOM summary that contains this selector
            for line in dom_summary.split("\n"):
                if action.target in line:
                    if DESTRUCTIVE_PATTERNS.search(line):
                        logger.info(f"Safety: destructive pattern in DOM context for target: {action.target}")
                        return True

        # Also check the reasoning text from the AI — sometimes the selector is innocuous
        # but the AI's reasoning reveals intent (e.g., "clicking the confirm order button")
        if action.reasoning and DESTRUCTIVE_PATTERNS.search(action.reasoning):
            logger.info(f"Safety: destructive pattern in reasoning: {action.reasoning}")
            return True

    # --- Navigate actions ---
    elif action_type == "navigate":
        # URL is in action.target or action.value for navigate actions
        url = action.target or action.value or ""
        if url and DESTRUCTIVE_URL_PATTERNS.search(url):
            # Lower severity — log it but still flag for confirmation
            logger.info(f"Safety: destructive URL pattern in navigation target: {url}")
            return True

    # --- Type actions ---
    elif action_type == "type":
        # Check if the target field matches sensitive field patterns
        if action.target and SENSITIVE_FIELD_PATTERNS.search(action.target):
            logger.info(f"Safety: sensitive field pattern in type target: {action.target}")
            return True

        # Check DOM context for the target field
        if action.target:
            # Strip CSS selector prefix (#, .) to match raw DOM attributes
            target_bare = action.target.lstrip("#.")
            for line in dom_summary.split("\n"):
                # Check if this line relates to our target (with or without CSS prefix)
                if action.target in line or target_bare in line:
                    if SENSITIVE_FIELD_PATTERNS.search(line):
                        logger.info(f"Safety: sensitive field in DOM context: {action.target}")
                        return True


    # --- File upload detection ---
    # Check if target references a file input
    if action.target and "file" in action.target.lower() and "input" in action.target.lower():
        logger.info(f"Safety: file upload detected: {action.target}")
        return True

    # Check DOM for file input type
    if action.target:
        for line in dom_summary.split("\n"):
            if action.target in line and 'type=file' in line.lower():
                logger.info(f"Safety: file input detected in DOM: {action.target}")
                return True

    return False


def format_confirmation_message(action: AgentAction, current_url: str) -> str:
    """
    Format a plain-English confirmation message for a destructive action.
    This is shown in both CLI (y/N prompt) and Web UI (Confirm/Cancel buttons).

    Args:
        action: The destructive AgentAction about to be executed.
        current_url: The current page URL.

    Returns:
        A formatted, human-readable confirmation message.
    """
    action_type = action.action.value
    target = action.target or "unknown element"

    # Build a plain-English description based on action type
    if action_type == "click":
        description = f"Click on '{target}'"
    elif action_type == "navigate":
        url = action.target or action.value or "unknown URL"
        description = f"Navigate to '{url}'"
    elif action_type == "type":
        value_preview = action.value[:50] + "..." if action.value and len(action.value) > 50 else action.value
        description = f"Type '{value_preview}' into '{target}'"
    else:
        description = f"Perform '{action_type}' on '{target}'"

    msg = (
        f"⚠️  CONFIRMATION NEEDED\n"
        f"Action: {description}\n"
        f"Reason: {action.reasoning}\n"
        f"Page:   {current_url}\n"
    )

    return msg
