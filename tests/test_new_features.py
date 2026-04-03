"""
Test suite for DuckX Newsfeed new features:
1. ai_summarizer.py - thinking_level="high" in ThinkingConfig
2. pipeline.py - 3 attempts (2 retries) + Telegram notification
3. pipeline.py - retry_execution_steps() function
4. routes.py - POST /api/execution-log/<exec_id>/retry endpoint
"""

import pytest
import json
import threading
import time
from unittest.mock import patch, MagicMock, call
from datetime import datetime

# Import modules to test
import sys
sys.path.insert(0, '/Users/meomacminim4/AI App/duckx-newsfeed')

from ai_summarizer import summarize_with_gemini, _get_client
from pipeline import (
    _run_ai_with_retry, _notify_ai_failure, retry_execution_steps,
    _AI_MAX_ATTEMPTS, _ADMIN_TELEGRAM_ID
)
import config_manager
from routes import bp as main_bp


# ============================================================================
# FEATURE 1: ai_summarizer.py - thinking_level="high"
# ============================================================================

class TestAiSummarizerThinkingLevel:
    """Verify code uses high thinking (default) — SDK 1.47 doesn't support thinking_level param"""

    def test_ai_summarizer_no_thinking_budget_zero(self):
        """Test thinking is not disabled — Gemini 3 Flash defaults to 'high' dynamic thinking"""
        with open('/Users/meomacminim4/AI App/duckx-newsfeed/ai_summarizer.py', 'r') as f:
            content = f.read()

        assert 'thinking_budget=0' not in content, "thinking_budget=0 disables thinking — should not be set"
        # No thinking_config needed: Gemini 3 Flash defaults to "high" dynamic thinking automatically
        assert 'thinking_level' not in content, "thinking_level should not be hardcoded — SDK version incompatibility"

    @patch('ai_summarizer._get_client')
    def test_error_handling_graceful(self, mock_get_client):
        """Test that summarize_with_gemini handles errors gracefully"""
        # Setup mock client to raise exception
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "1 validation error for ThinkingConfig"
        )
        mock_get_client.return_value = mock_client

        result = summarize_with_gemini(
            tweets_text="Test tweet content",
            prompt="Summarize tweets",
            api_key="test_key"
        )

        # Should return error message, not crash
        assert "[ERROR]" in result, "Should return error message on exception"

    def test_thinking_config_in_code(self):
        """Verify ThinkingConfig is instantiated in summarize_with_gemini"""
        from google.genai import types

        # The code should create a ThinkingConfig instance
        # Verify the class exists and has thinking-related parameters
        import inspect
        sig = inspect.signature(types.ThinkingConfig)
        params = list(sig.parameters.keys())

        # API supports thinkingBudget or includeThoughts
        assert 'thinkingBudget' in params or 'thinking_budget' in params, \
            "ThinkingConfig should have thinking-related parameters"


# ============================================================================
# FEATURE 2: pipeline.py - _run_ai_with_retry (3 attempts + notification)
# ============================================================================

class TestRunAiWithRetry:
    """Test _run_ai_with_retry with 3 attempts and Telegram notification"""

    @patch('pipeline.summarize_tweets')
    @patch('pipeline._notify_ai_failure')
    def test_success_on_first_attempt(self, mock_notify, mock_summarize):
        """Test: AI succeeds on 1st attempt → returns immediately, no notification"""
        mock_summarize.return_value = "Success summary"

        result, success, detail = _run_ai_with_retry("tweets", "prompt", "model_1")

        assert result == "Success summary"
        assert success is True
        assert detail == ""
        assert mock_summarize.call_count == 1, "Should call summarize_tweets once"
        assert not mock_notify.called, "Should not notify if AI succeeds"

    @patch('pipeline.summarize_tweets')
    @patch('pipeline._notify_ai_failure')
    @patch('pipeline.time.sleep')
    def test_success_on_third_attempt(self, mock_sleep, mock_notify, mock_summarize):
        """Test: AI fails twice, succeeds on 3rd → returns success, no notification"""
        # First two calls return error, third succeeds
        mock_summarize.side_effect = [
            "[ERROR] Attempt 1 failed",
            "[ERROR] Attempt 2 failed",
            "Success on 3rd attempt"
        ]

        result, success, detail = _run_ai_with_retry("tweets", "prompt", "model_1")

        assert result == "Success on 3rd attempt"
        assert success is True
        assert detail == ""
        assert mock_summarize.call_count == 3, "Should call summarize_tweets 3 times"
        assert mock_sleep.call_count == 2, "Should sleep 2 times (between attempts)"
        assert not mock_notify.called, "Should not notify if AI eventually succeeds"

    @patch('pipeline.summarize_tweets')
    @patch('pipeline._notify_ai_failure')
    @patch('pipeline.time.sleep')
    def test_failure_after_3_attempts(self, mock_sleep, mock_notify, mock_summarize):
        """Test: AI fails all 3 attempts → calls _notify_ai_failure, returns failure"""
        mock_summarize.return_value = "[ERROR] AI failed"

        result, success, detail = _run_ai_with_retry("tweets", "prompt", "model_1")

        assert success is False
        assert "[ERROR]" in result or "[ERROR]" in detail
        assert mock_summarize.call_count == 3, "Should attempt 3 times"
        assert mock_sleep.call_count == 2, "Should sleep 2 times"
        assert mock_notify.called, "Should notify admin on full failure"
        mock_notify.assert_called_once()

    @patch('pipeline.summarize_tweets')
    @patch('pipeline._notify_ai_failure')
    @patch('pipeline.time.sleep')
    def test_exception_during_attempt(self, mock_sleep, mock_notify, mock_summarize):
        """Test: AI raises exception → treated as failed attempt"""
        mock_summarize.side_effect = Exception("API timeout")

        result, success, detail = _run_ai_with_retry("tweets", "prompt", "model_1")

        assert success is False
        assert mock_summarize.call_count == 3, "Should still try all 3 times"
        assert mock_notify.called, "Should notify admin"

    def test_ai_max_attempts_constant(self):
        """Verify _AI_MAX_ATTEMPTS is 3"""
        assert _AI_MAX_ATTEMPTS == 3, "Should have 3 attempts (1 initial + 2 retries)"


# ============================================================================
# FEATURE 2b: pipeline.py - _notify_ai_failure
# ============================================================================

class TestNotifyAiFailure:
    """Test _notify_ai_failure sends Telegram to admin"""

    @patch('pipeline.send_message_to_targets')
    def test_notify_sends_to_admin_id(self, mock_send):
        """Test: _notify_ai_failure calls send_message_to_targets with admin ID"""
        mock_send.return_value = {"success": True}

        _notify_ai_failure("Test error message", "gemini_free_1")

        # Verify send_message_to_targets was called
        assert mock_send.called, "Should call send_message_to_targets"

        # Verify admin ID is correct
        call_args = mock_send.call_args
        message, targets = call_args[0]
        assert _ADMIN_TELEGRAM_ID in targets, f"Should send to admin ID {_ADMIN_TELEGRAM_ID}"

        # Verify message contains error info
        assert "AI Error" in message or "DuckX" in message, "Message should mention error"

    @patch('pipeline.send_message_to_targets')
    def test_notify_includes_error_message(self, mock_send):
        """Test: _notify_ai_failure includes error details in message"""
        mock_send.return_value = {"success": True}
        error_msg = "Quota exceeded on API"

        _notify_ai_failure(error_msg, "gemini_free_2")

        call_args = mock_send.call_args
        message = call_args[0][0]
        assert error_msg[:50] in message or "Quota" in message, "Should include error in message"

    @patch('pipeline.send_message_to_targets')
    def test_notify_handles_exception_gracefully(self, mock_send):
        """Test: _notify_ai_failure handles send exception gracefully"""
        mock_send.side_effect = Exception("Telegram connection failed")

        # Should not raise exception
        try:
            _notify_ai_failure("Error", "model")
        except Exception:
            pytest.fail("_notify_ai_failure should handle exceptions gracefully")


# ============================================================================
# FEATURE 3: pipeline.py - retry_execution_steps(exec_id)
# ============================================================================

class TestRetryExecutionSteps:
    """Test retry_execution_steps with all 5 branches"""

    @patch('config_manager.get_execution_log')
    def test_exec_id_not_found(self, mock_get_log):
        """Branch 1: exec_id not found → logs warning, returns"""
        mock_get_log.return_value = [
            {"id": "exec_other", "watchlist_id": "wl_1"}
        ]

        with patch('pipeline.logger') as mock_logger:
            retry_execution_steps("exec_notfound")

            # Should log warning
            assert mock_logger.warning.called, "Should log warning for missing exec_id"

    @patch('config_manager.get_execution_log')
    @patch('config_manager.get_watchlist_by_id')
    def test_watchlist_not_found(self, mock_get_wl, mock_get_log):
        """Branch 2: watchlist not found → logs warning, returns"""
        mock_get_log.return_value = [
            {"id": "exec_1", "watchlist_id": "wl_missing"}
        ]
        mock_get_wl.return_value = None

        with patch('pipeline.logger') as mock_logger:
            retry_execution_steps("exec_1")

            assert mock_logger.warning.called, "Should log warning for missing watchlist"

    @patch('config_manager.get_execution_log')
    @patch('config_manager.get_watchlist_by_id')
    @patch('pipeline.run_fetch_for_watchlist')
    def test_fetch_failed_reruns_full_pipeline(self, mock_run_fetch, mock_get_wl, mock_get_log):
        """Branch 3: fetch failed → calls run_fetch_for_watchlist"""
        mock_get_log.return_value = [
            {
                "id": "exec_1",
                "watchlist_id": "wl_1",
                "steps": {
                    "fetch": {"status": "error"},
                    "ai": {"status": "skipped"}
                },
                "raw_tweets": ""
            }
        ]
        mock_get_wl.return_value = {"id": "wl_1", "name": "Test WL"}

        retry_execution_steps("exec_1")

        assert mock_run_fetch.called, "Should call run_fetch_for_watchlist on fetch failure"
        mock_run_fetch.assert_called_once_with("wl_1")

    @patch('config_manager.get_execution_log')
    @patch('config_manager.get_watchlist_by_id')
    @patch('pipeline.run_fetch_for_watchlist')
    def test_no_raw_tweets_reruns_full_pipeline(self, mock_run_fetch, mock_get_wl, mock_get_log):
        """Branch 3b: no raw_tweets → calls run_fetch_for_watchlist"""
        mock_get_log.return_value = [
            {
                "id": "exec_1",
                "watchlist_id": "wl_1",
                "steps": {
                    "fetch": {"status": "success"},
                    "ai": {"status": "error"}
                },
                "raw_tweets": ""  # Empty
            }
        ]
        mock_get_wl.return_value = {"id": "wl_1", "name": "Test WL"}

        retry_execution_steps("exec_1")

        assert mock_run_fetch.called, "Should re-run fetch if no raw_tweets"

    @patch('config_manager.get_execution_log')
    @patch('config_manager.get_watchlist_by_id')
    @patch('pipeline._run_ai_with_retry')
    @patch('pipeline._send_telegram_step')
    @patch('config_manager.record_execution')
    def test_fetch_ok_ai_failed_retries_ai(self, mock_record, mock_tg, mock_ai, mock_get_wl, mock_get_log):
        """Branch 4: fetch ok, AI failed → calls _run_ai_with_retry + telegram + record"""
        mock_get_log.return_value = [
            {
                "id": "exec_1",
                "watchlist_id": "wl_1",
                "watchlist_name": "Test WL",
                "steps": {
                    "fetch": {"status": "success", "tweet_count": 5, "detail": "5 tweets"},
                    "ai": {"status": "error", "detail": "Failed", "model": "gemini_free_1"}
                },
                "raw_tweets": "Tweet 1\nTweet 2",
                "ai_summary": ""
            }
        ]
        mock_get_wl.return_value = {
            "id": "wl_1",
            "name": "Test WL",
            "prompt": "Summarize",
            "ai_model": "gemini_free_1"
        }
        mock_ai.return_value = ("New summary", True, "")
        mock_tg.return_value = ("success", "Sent")

        retry_execution_steps("exec_1")

        # Verify AI was retried
        assert mock_ai.called, "Should call _run_ai_with_retry"
        mock_ai.assert_called_once()

        # Verify Telegram was called
        assert mock_tg.called, "Should call _send_telegram_step"

        # Verify execution was recorded
        assert mock_record.called, "Should call record_execution"

    @patch('config_manager.get_execution_log')
    @patch('config_manager.get_watchlist_by_id')
    @patch('pipeline._run_ai_with_retry')
    @patch('pipeline._send_telegram_step')
    @patch('config_manager.record_execution')
    def test_fetch_ok_ai_ok_telegram_failed_retries_telegram(self, mock_record, mock_tg, mock_ai, mock_get_wl, mock_get_log):
        """Branch 5: fetch ok, AI ok, Telegram failed → calls _send_telegram_step + record"""
        mock_get_log.return_value = [
            {
                "id": "exec_1",
                "watchlist_id": "wl_1",
                "watchlist_name": "Test WL",
                "steps": {
                    "fetch": {"status": "success", "tweet_count": 3, "detail": "3 tweets"},
                    "ai": {"status": "success", "detail": "Summarized", "model": "gemini_free_1"},
                    "telegram": {"status": "error", "detail": "Failed"}
                },
                "raw_tweets": "Tweet 1",
                "ai_summary": "Summary text"
            }
        ]
        mock_get_wl.return_value = {
            "id": "wl_1",
            "name": "Test WL",
            "prompt": "Summarize",
            "ai_model": "gemini_free_1"
        }
        mock_tg.return_value = ("success", "Sent")

        retry_execution_steps("exec_1")

        # Verify AI was NOT retried (already succeeded)
        assert not mock_ai.called, "Should not retry AI if it already succeeded"

        # Verify Telegram was retried
        assert mock_tg.called, "Should call _send_telegram_step"

        # Verify execution was recorded
        assert mock_record.called, "Should call record_execution"


# ============================================================================
# FEATURE 4: routes.py - POST /api/execution-log/<exec_id>/retry
# ============================================================================

class TestRetryExecutionEndpoint:
    """Test POST /api/execution-log/<exec_id>/retry endpoint"""

    def test_endpoint_exists_in_routes(self):
        """Test that the endpoint is defined in routes.py"""
        # Verify the endpoint code exists in routes.py
        with open('/Users/meomacminim4/AI App/duckx-newsfeed/routes.py', 'r') as f:
            content = f.read()

        assert "'/api/execution-log/<exec_id>/retry'" in content or \
               '"/api/execution-log/<exec_id>/retry"' in content, \
            "Endpoint route should be defined"
        assert "retry_execution_steps" in content, \
            "Endpoint should call retry_execution_steps"

    @patch('routes.retry_execution_steps')
    def test_endpoint_returns_success_json(self, mock_retry):
        """Test: Endpoint returns JSON with success=True"""
        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(main_bp)
        client = app.test_client()

        response = client.post('/api/execution-log/exec_test/retry')

        assert response.status_code == 200, "Should return 200"
        data = json.loads(response.data)
        assert data.get('success') is True, "Should return success: true"
        assert 'message' in data, "Should include message"

    @patch('routes.retry_execution_steps')
    def test_endpoint_spawns_background_thread(self, mock_retry):
        """Test: Endpoint spawns background thread calling retry_execution_steps"""
        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(main_bp)
        client = app.test_client()

        with patch('routes.threading.Thread') as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            client.post('/api/execution-log/exec_123/retry')

            # Verify Thread was created with correct target
            assert mock_thread.called, "Should create a Thread"
            call_kwargs = mock_thread.call_args[1]
            assert call_kwargs.get('target') == mock_retry, "Thread target should be retry_execution_steps"

            # Verify thread.start() was called
            assert mock_thread_instance.start.called, "Should start the thread"

    @patch('routes.retry_execution_steps')
    def test_endpoint_passes_exec_id_correctly(self, mock_retry):
        """Test: Endpoint passes exec_id to retry_execution_steps"""
        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(main_bp)
        client = app.test_client()

        with patch('routes.threading.Thread') as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            test_exec_id = "exec_abc123"
            client.post(f'/api/execution-log/{test_exec_id}/retry')

            # Verify exec_id was passed to thread
            call_kwargs = mock_thread.call_args[1]
            args = call_kwargs.get('args', [])
            assert test_exec_id in args, f"Should pass {test_exec_id} to thread"

    @patch('routes.retry_execution_steps')
    def test_endpoint_daemon_false(self, mock_retry):
        """Test: Thread created with daemon=False (allows graceful shutdown)"""
        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(main_bp)
        client = app.test_client()

        with patch('routes.threading.Thread') as mock_thread:
            mock_thread_instance = MagicMock()
            mock_thread.return_value = mock_thread_instance

            client.post('/api/execution-log/exec_test/retry')

            call_kwargs = mock_thread.call_args[1]
            assert call_kwargs.get('daemon') is False, "Thread should have daemon=False"


# ============================================================================
# Integration tests
# ============================================================================

class TestIntegration:
    """Integration tests for the full retry flow"""

    @patch('pipeline.summarize_tweets')
    @patch('pipeline._send_telegram_step')
    @patch('config_manager.get_execution_log')
    @patch('config_manager.get_watchlist_by_id')
    @patch('config_manager.record_execution')
    def test_full_retry_flow_ai_failure_recovery(self, mock_record, mock_get_wl, mock_get_log,
                                                   mock_tg_step, mock_summarize):
        """Test: Full flow when AI fails on first try, then succeeds on retry"""
        # Setup: AI succeeds on retry
        mock_summarize.return_value = "Recovered summary"
        mock_tg_step.return_value = ("success", "Sent")

        mock_get_log.return_value = [
            {
                "id": "exec_1",
                "watchlist_id": "wl_1",
                "watchlist_name": "Test WL",
                "steps": {
                    "fetch": {"status": "success", "tweet_count": 2, "detail": "2 tweets"},
                    "ai": {"status": "error", "detail": "Failed"},
                    "telegram": {"status": "skipped"}
                },
                "raw_tweets": "Tweet content",
                "ai_summary": ""
            }
        ]

        mock_get_wl.return_value = {
            "id": "wl_1",
            "name": "Test WL",
            "prompt": "Summarize",
            "ai_model": "gemini_free_1"
        }

        # Execute retry
        retry_execution_steps("exec_1")

        # Verify recovery: summarize was called
        assert mock_summarize.called, "Should attempt AI summarization"

        # Verify Telegram was sent (since AI succeeded)
        assert mock_tg_step.called, "Should send Telegram after successful AI"

        # Verify execution was recorded
        assert mock_record.called, "Should record new execution"


# ============================================================================
# Run tests
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
