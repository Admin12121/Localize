"""Browser policy checks run even without the optional Chromium dependency."""
import pytest
from web_bridge.web.client import Bridge
from web_bridge.web.policy import BridgeError

def test_browser_validation_precedes_worker_launch():
    bridge=Bridge({'lab':'http://127.0.0.1:12345'},allow_private=True)
    with pytest.raises(BridgeError,match='Unknown browser action'):
        bridge.browser_action('lab',action='invalid')
    with pytest.raises(BridgeError,match='selector'):
        bridge.browser_action('lab',action='click')
    assert bridge._browser_process is None
