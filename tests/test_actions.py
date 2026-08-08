import pytest
from core.actions import AgentAction, ActionType, ActionParseError, parse_and_validate

def test_valid_json():
    """Test valid JSON response."""
    raw = '{"reasoning": "Go to google", "action": "navigate", "target": "https://google.com"}'
    action = parse_and_validate(raw)
    assert action.action == ActionType.navigate
    assert action.target == "https://google.com"

def test_markdown_fences():
    """Test JSON wrapped in markdown fences."""
    raw = '```json\n{"reasoning": "test", "action": "click", "target": "#btn"}\n```'
    action = parse_and_validate(raw)
    assert action.action == ActionType.click
    assert action.target == "#btn"

def test_json_with_prose():
    """Test JSON with prose before and after."""
    raw = 'Here is my action:\n{"reasoning": "test", "action": "type", "target": "#input", "value": "hello"}\nDone.'
    action = parse_and_validate(raw)
    assert action.action == ActionType.type
    assert action.value == "hello"

def test_missing_required_fields():
    """Test missing required fields raises ActionParseError."""
    raw = '{"reasoning": "test"}'
    with pytest.raises(ActionParseError):
        parse_and_validate(raw)

def test_wrong_field_types():
    """Test wrong field types raises ActionParseError."""
    raw = '{"reasoning": "test", "action": "fly"}'
    with pytest.raises(ActionParseError):
        parse_and_validate(raw)

def test_empty_string():
    """Test empty string raises ActionParseError."""
    with pytest.raises(ActionParseError):
        parse_and_validate("")

def test_non_json_garbage():
    """Test non-JSON garbage raises ActionParseError."""
    with pytest.raises(ActionParseError):
        parse_and_validate("Just some text that is not json at all")

def test_multiple_json_objects():
    """Test multiple JSON objects uses only the first one."""
    raw = '{"reasoning": "first", "action": "click", "target": "#1"}\n{"reasoning": "second", "action": "click", "target": "#2"}'
    action = parse_and_validate(raw)
    assert action.target == "#1"

def test_extra_fields():
    """Test extra fields are ignored."""
    raw = '{"reasoning": "test", "action": "wait", "extra": "stuff"}'
    action = parse_and_validate(raw)
    assert action.action == ActionType.wait
    assert not hasattr(action, "extra")

def test_all_action_types():
    """Test all ActionType values parse correctly."""
    types = ["navigate", "click", "type", "scroll", "extract", "screenshot", "wait", "complete", "abort"]
    for t in types:
        raw = f'{{"reasoning": "test", "action": "{t}"}}'
        action = parse_and_validate(raw)
        assert action.action.value == t
