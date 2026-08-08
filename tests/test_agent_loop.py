"""
Tests for the Aegis agent loop — loop detection, failure handling,
and terminal state behavior.

Uses mocked browser, AI client, and history to isolate the agent loop logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.agent import AegisAgent
from core.actions import AgentAction, ActionType
from core.browser import ExecutionError


from config.settings import settings

@pytest.fixture(autouse=True)
def enable_safety():
    old = getattr(settings, 'ENABLE_SAFETY_CONFIRMATION', False)
    settings.ENABLE_SAFETY_CONFIRMATION = True
    yield
    settings.ENABLE_SAFETY_CONFIRMATION = old

def _make_agent(browser_mock, ai_mock, history_mock=None):
    """Create an AegisAgent with mocked dependencies injected."""
    agent = AegisAgent()
    agent.browser = browser_mock
    agent.ai_client = ai_mock
    if history_mock is None:
        history_mock = AsyncMock()
        history_mock.create_session.return_value = "test-session-id"
        history_mock.get_recent_actions.return_value = []
        history_mock.get_session_summary.return_value = {"status": "running"}
    agent.history = history_mock
    return agent


def _make_browser_mock(url="https://example.com"):
    """Create a standard browser mock."""
    mock = AsyncMock()
    mock.get_current_url.return_value = url
    mock.capture_screenshot.return_value = "base64screenshot"
    mock.extract_condensed_dom.return_value = "[button#btn] \"Click Me\""
    mock.execute_action.return_value = "Action executed"
    return mock


@pytest.mark.asyncio
async def test_same_action_3x_triggers_abort():
    """Test: same action 3x consecutively triggers abort."""
    browser_mock = _make_browser_mock()
    ai_mock = AsyncMock()

    # Return the exact same action repeatedly
    action = AgentAction(reasoning="Looping", action=ActionType.click, target="#stuck")
    ai_mock.get_next_action.return_value = action

    agent = _make_agent(browser_mock, ai_mock)
    result = await agent.run_task("test task", headless=True, max_steps=10)

    # Agent should have detected the loop and stopped
    agent.history.update_session_status.assert_called()
    # Check that it stopped before max_steps
    call_count = ai_mock.get_next_action.call_count
    assert call_count <= 5  # Should abort well before 10 steps


@pytest.mark.asyncio
async def test_consecutive_errors_triggers_abort():
    """Test: 3 consecutive execution errors triggers abort."""
    browser_mock = _make_browser_mock()
    ai_mock = AsyncMock()

    # Simulate execution failure with ExecutionError
    browser_mock.execute_action.side_effect = ExecutionError("Browser error")

    # Need varying actions to avoid loop detection triggering first
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return AgentAction(reasoning=f"Step {call_count}", action=ActionType.click, target=f"#btn{call_count}")
    ai_mock.get_next_action.side_effect = side_effect

    agent = _make_agent(browser_mock, ai_mock)
    result = await agent.run_task("test task", headless=True, max_steps=10)

    # Should abort after 3 consecutive errors
    assert call_count <= 5


@pytest.mark.asyncio
async def test_max_steps_triggers_timeout():
    """Test: max steps reached triggers timeout."""
    browser_mock = _make_browser_mock()
    ai_mock = AsyncMock()

    # Return varying actions so loop detection doesn't fire, and change URLs
    call_count = 0
    def ai_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return AgentAction(reasoning=f"Step {call_count}", action=ActionType.scroll, target=f"#section{call_count}", value="down")

    ai_mock.get_next_action.side_effect = ai_side_effect
    # Change URL each step to avoid stuck-URL detection
    browser_mock.get_current_url.side_effect = [f"https://example.com/page{i}" for i in range(20)]

    agent = _make_agent(browser_mock, ai_mock)
    result = await agent.run_task("test task", headless=True, max_steps=5)

    # Should have run exactly 5 steps
    assert call_count == 5


@pytest.mark.asyncio
async def test_complete_action_ends_loop():
    """Test: complete action properly ends the loop."""
    browser_mock = _make_browser_mock()
    ai_mock = AsyncMock()

    ai_mock.get_next_action.return_value = AgentAction(
        reasoning="Done", action=ActionType.complete, value="Task finished successfully"
    )

    agent = _make_agent(browser_mock, ai_mock)
    result = await agent.run_task("test task", headless=True, max_steps=25)

    # Should have called AI exactly once (complete on first step)
    assert ai_mock.get_next_action.call_count == 1
    # Session should be marked completed
    agent.history.update_session_status.assert_called_with("test-session-id", "completed")


@pytest.mark.asyncio
async def test_abort_action_ends_loop():
    """Test: abort action properly ends the loop."""
    browser_mock = _make_browser_mock()
    ai_mock = AsyncMock()

    ai_mock.get_next_action.return_value = AgentAction(
        reasoning="Cannot proceed", action=ActionType.abort, value="Login wall encountered"
    )

    agent = _make_agent(browser_mock, ai_mock)
    result = await agent.run_task("test task", headless=True, max_steps=25)

    # Should have called AI exactly once
    assert ai_mock.get_next_action.call_count == 1
    # Session should be marked aborted
    agent.history.update_session_status.assert_called_with("test-session-id", "aborted")


@pytest.mark.asyncio
async def test_destructive_action_without_confirmation_aborts():
    """Test: destructive action without confirmation handler aborts."""
    browser_mock = _make_browser_mock()
    ai_mock = AsyncMock()

    # Action with a destructive target (contains "delete")
    action = AgentAction(reasoning="Delete item", action=ActionType.click, target="#delete-account")
    ai_mock.get_next_action.return_value = action

    agent = _make_agent(browser_mock, ai_mock)
    # No confirmation handler set — default is None, so agent should abort
    result = await agent.run_task("test task", headless=True, max_steps=10)

    # Should have stopped after first step (no confirmation handler = rejection)
    assert ai_mock.get_next_action.call_count == 1
    agent.history.update_session_status.assert_called_with("test-session-id", "stopped")
