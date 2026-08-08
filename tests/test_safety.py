import pytest
from core.actions import AgentAction, ActionType
from core.safety import classify, format_confirmation_message
from config.settings import settings

@pytest.fixture(autouse=True)
def enable_safety():
    old = getattr(settings, 'ENABLE_SAFETY_CONFIRMATION', False)
    settings.ENABLE_SAFETY_CONFIRMATION = True
    yield
    settings.ENABLE_SAFETY_CONFIRMATION = old

def test_click_buy_now():
    """Test clicking 'Buy Now' is destructive."""
    action = AgentAction(reasoning="Buy item", action=ActionType.click, target="#buy")
    assert classify(action, '<button id="buy">Buy Now</button>') is True

def test_click_submit_order():
    """Test clicking 'Submit Order' is destructive."""
    action = AgentAction(reasoning="Submit order", action=ActionType.click, target="#submit")
    assert classify(action, '<button id="submit">Submit Order</button>') is True

def test_click_delete_account():
    """Test clicking 'Delete Account' is destructive."""
    action = AgentAction(reasoning="Delete user account", action=ActionType.click, target="#delete")
    assert classify(action, '<button id="delete">Delete Account</button>') is True

def test_click_remove_item():
    """Test clicking 'Remove Item' is destructive."""
    action = AgentAction(reasoning="Remove item from cart", action=ActionType.click, target="#remove")
    assert classify(action, '<button id="remove">Remove Item</button>') is True

def test_click_checkout():
    """Test clicking 'Checkout' is destructive."""
    action = AgentAction(reasoning="Go to checkout", action=ActionType.click, target="#checkout")
    assert classify(action, '<button id="checkout">Checkout</button>') is True

def test_click_about_us():
    """Test clicking a regular link is NOT destructive."""
    action = AgentAction(reasoning="View about us page", action=ActionType.click, target="#about")
    assert classify(action, '<a id="about" href="/about">About Us</a>') is False

def test_click_search_button():
    """Test clicking search button is NOT destructive."""
    action = AgentAction(reasoning="Search site", action=ActionType.click, target="#search")
    assert classify(action, '<button id="search">Search</button>') is False

def test_navigate_checkout():
    """Test navigating to /checkout is destructive."""
    action = AgentAction(reasoning="Go to checkout URL", action=ActionType.navigate, target="https://example.com/checkout")
    assert classify(action, '') is True

def test_navigate_about():
    """Test navigating to /about is NOT destructive."""
    action = AgentAction(reasoning="Go to about URL", action=ActionType.navigate, target="https://example.com/about")
    assert classify(action, '') is False

def test_type_password():
    """Test typing into a password field is destructive."""
    action = AgentAction(reasoning="Enter password", action=ActionType.type, target="#pwd", value="secret")
    assert classify(action, '<input id="pwd" type="password">') is True

def test_type_search():
    """Test typing into a search field is NOT destructive."""
    action = AgentAction(reasoning="Enter search query", action=ActionType.type, target="#search", value="shoes")
    assert classify(action, '<input id="search" type="text">') is False

def test_click_submit_in_form():
    """Test clicking a generic submit button in a form context is NOT destructive."""
    action = AgentAction(reasoning="Execute search form", action=ActionType.click, target="#go")
    assert classify(action, '<form><button id="go" type="submit">Send</button></form>') is False

def test_format_confirmation_message():
    """Test format_confirmation_message produces readable output."""
    action = AgentAction(reasoning="Buy product", action=ActionType.click, target="#buy")
    msg = format_confirmation_message(action, "https://example.com/product")
    assert "https://example.com/product" in msg
    assert "click" in msg.lower()
    assert "#buy" in msg
    assert "Buy product" in msg
