import json
import pytest
from test_bridge import app

def test_real_chromium_navigation_dom_js_diagnostics_and_off_origin_block(app):
    pytest.importorskip('playwright')
    try:
        result=app.browser_action('lab','visit')
        assert '<form' in result['html']
        app.browser_action('lab','fill',selector='input[name=user]',value='ctf-browser-test')
        result=app.browser_action('lab','evaluate',script="document.querySelector('input').value")
        assert json.loads(result['value'])=='ctf-browser-test'
        app.browser_action('lab','evaluate',script="fetch('http://off-scope.invalid/x').catch(() => 'blocked')")
        diagnostics=app.browser_action('lab','diagnostics')
        assert any(e['type']=='blocked_or_failed' for e in diagnostics['events'])
        assert any(e['type']=='network' and e.get('status')==200 for e in diagnostics['events'])
        app.reset_session('lab')
    finally:
        if app._browser_process:app._browser_process.close()
