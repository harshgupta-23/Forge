import pytest
from unittest.mock import MagicMock, patch
import tools.browser_action as ba


def test_browser_action_singleton_reuse():
    # Reset globals before test
    ba.close_browser()

    mock_sync_fn = MagicMock()
    mock_p_instance = MagicMock()
    mock_sync_fn.return_value.start.return_value = mock_p_instance

    mock_context = MagicMock()
    mock_context.pages = []
    mock_page1 = MagicMock()
    mock_page1.title.return_value = "Page 1"
    mock_page1.inner_text.return_value = "Page content 1"

    mock_page2 = MagicMock()
    mock_page2.title.return_value = "Page 2"
    mock_page2.inner_text.return_value = "Page content 2"

    mock_page3 = MagicMock()
    mock_page3.title.return_value = "Page 3"
    mock_page3.inner_text.return_value = "Page content 3"

    mock_context.new_page.side_effect = [mock_page1, mock_page2, mock_page3]
    mock_p_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("tools.browser_action._ensure_playwright", return_value=mock_sync_fn):
        # Call 1
        res1 = ba.browser_action.invoke({"instructions": "Go to https://example.com/1 and extract text"})
        assert "Page (Page 1)" in res1
        assert mock_page1.close.call_count == 1
        assert mock_context.close.call_count == 0

        # Call 2
        res2 = ba.browser_action.invoke({"instructions": "Go to https://example.com/2 and extract text"})
        assert "Page (Page 2)" in res2
        assert mock_page2.close.call_count == 1
        assert mock_context.close.call_count == 0

        # Call 3
        res3 = ba.browser_action.invoke({"instructions": "Go to https://example.com/3 and extract text"})
        assert "Page (Page 3)" in res3
        assert mock_page3.close.call_count == 1
        assert mock_context.close.call_count == 0

        # Verify browser context was only launched once across all 3 calls
        assert mock_p_instance.chromium.launch_persistent_context.call_count == 1
        assert mock_context.new_page.call_count == 3

        # Now shut down
        ba.close_browser()
        assert mock_context.close.call_count == 1
        assert mock_p_instance.stop.call_count == 1
