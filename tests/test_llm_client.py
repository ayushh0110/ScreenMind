"""Comprehensive tests for LLM client module."""
import pytest
import threading
from unittest.mock import patch, MagicMock, PropertyMock
import httpx

from screenmind.engine.llm_client import (
    InferenceCancelled, cancel_current_inference, is_inference_active,
    chat, chat_with_images, transcribe_audio, generate, is_available,
    get_server_status, _cancel_event, _client_lock,
)


class TestInferenceCancellation:
    """Tests for the GPU priority / cancellation system."""

    def test_inference_cancelled_is_exception(self):
        with pytest.raises(InferenceCancelled):
            raise InferenceCancelled("test")

    def test_is_inference_active_default_false(self):
        assert is_inference_active() is False

    def test_cancel_no_active_client(self):
        """Cancel when nothing is running doesn't crash."""
        cancel_current_inference()

    def test_cancel_sets_event(self):
        """Cancel sets the cancel event flag."""
        _cancel_event.clear()
        cancel_current_inference()
        assert _cancel_event.is_set()
        _cancel_event.clear()

    @patch("screenmind.engine.llm_client.httpx.Client")
    def test_chat_clears_cancel_event_on_start(self, mock_client_cls):
        """Each chat() call clears stale cancel flags."""
        _cancel_event.set()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.post.return_value = mock_resp
        chat([{"role": "user", "content": "test"}])
        # Flag should be cleared at start of chat()
        assert not _cancel_event.is_set()

    @patch("screenmind.engine.llm_client.httpx.Client")
    def test_chat_raises_cancelled_when_flag_set(self, mock_client_cls):
        """If cancel flag is set during request, InferenceCancelled is raised."""
        def side_effect(*args, **kwargs):
            _cancel_event.set()
            raise httpx.ConnectError("closed")
        mock_client_cls.return_value.post.side_effect = side_effect
        with pytest.raises(InferenceCancelled):
            chat([{"role": "user", "content": "test"}])
        _cancel_event.clear()

    @patch("screenmind.engine.llm_client.httpx.Client")
    def test_active_client_set_during_request(self, mock_client_cls):
        """_active_client is set during request and cleared after."""
        active_during = []

        def capture_post(*args, **kwargs):
            active_during.append(is_inference_active())
            resp = MagicMock()
            resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
            resp.raise_for_status = MagicMock()
            return resp

        mock_client_cls.return_value.post.side_effect = capture_post
        chat([{"role": "user", "content": "test"}])
        assert active_during[0] is True
        assert is_inference_active() is False


class TestChat:
    """Tests for the chat() function."""

    @patch("screenmind.engine.llm_client.httpx.Client")
    def test_chat_returns_content(self, mock_client_cls):
        """chat() returns the assistant message content."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "Hello!"}}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.post.return_value = mock_resp
        result = chat([{"role": "user", "content": "hi"}])
        assert result == "Hello!"

    @patch("screenmind.engine.llm_client.httpx.Client")
    def test_chat_sends_correct_payload(self, mock_client_cls):
        """chat() sends messages, temperature, max_tokens in payload."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.post.return_value = mock_resp

        messages = [{"role": "user", "content": "test"}]
        chat(messages, temperature=0.5, max_tokens=512)

        call_args = mock_client_cls.return_value.post.call_args
        payload = call_args[1]["json"]
        assert payload["messages"] == messages
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 512
        assert payload["cache_prompt"] is True

    @patch("screenmind.engine.llm_client.httpx.Client")
    def test_cache_prompt_sent_from_every_entry_point(self, mock_client_cls):
        """generate(), chat_with_images() and transcribe_audio() all reach
        llama-server through chat(), so all of them send cache_prompt."""
        from screenmind.engine.llm_client import chat_with_images, transcribe_audio
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_resp.raise_for_status = MagicMock()
        post = mock_client_cls.return_value.post
        post.return_value = mock_resp

        generate("summarize my day")
        chat_with_images("describe", [b"\xff\xd8jpeg"])
        with patch("screenmind.engine.model_manager.is_audio_capable", return_value=True):
            transcribe_audio(b"RIFFwav")

        assert post.call_count == 3
        assert all(c[1]["json"]["cache_prompt"] is True for c in post.call_args_list)

    @patch("screenmind.engine.llm_client.httpx.Client")
    def test_chat_raises_on_http_error(self, mock_client_cls):
        """chat() raises on non-cancelled HTTP errors."""
        mock_client_cls.return_value.post.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        with pytest.raises(httpx.HTTPStatusError):
            chat([{"role": "user", "content": "test"}])


class TestChatWithImages:
    """Tests for chat_with_images()."""

    @patch("screenmind.engine.llm_client.chat")
    def test_encodes_images_as_base64(self, mock_chat):
        """Images are base64 encoded in the message."""
        mock_chat.return_value = "I see an image"
        result = chat_with_images("describe this", [b"\xff\xd8\xff\xe0test"])
        assert result == "I see an image"

        call_args = mock_chat.call_args[1] if mock_chat.call_args[1] else {}
        messages = mock_chat.call_args[0][0]
        user_msg = messages[-1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], list)
        assert user_msg["content"][0]["type"] == "text"
        assert user_msg["content"][1]["type"] == "image_url"

    @patch("screenmind.engine.llm_client.chat")
    def test_includes_system_message(self, mock_chat):
        """System message is prepended when provided."""
        mock_chat.return_value = "ok"
        chat_with_images("describe", [b"img"], system="You are helpful")
        messages = mock_chat.call_args[0][0]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful"

    @patch("screenmind.engine.llm_client.chat")
    def test_multiple_images(self, mock_chat):
        """Multiple images are all included."""
        mock_chat.return_value = "ok"
        chat_with_images("compare", [b"img1", b"img2", b"img3"])
        messages = mock_chat.call_args[0][0]
        user_content = messages[-1]["content"]
        image_parts = [p for p in user_content if p["type"] == "image_url"]
        assert len(image_parts) == 3


class TestTranscribeAudio:
    """Tests for transcribe_audio()."""

    @patch("screenmind.engine.llm_client.chat")
    @patch("screenmind.engine.model_manager.is_audio_capable", return_value=True)
    def test_sends_audio_as_input_audio(self, _cap, mock_chat):
        """Audio bytes are sent as input_audio type."""
        mock_chat.return_value = "Hello world"
        result = transcribe_audio(b"fake wav bytes")
        assert result == "Hello world"
        messages = mock_chat.call_args[0][0]
        user_content = messages[0]["content"]
        audio_part = [p for p in user_content if p["type"] == "input_audio"]
        assert len(audio_part) == 1
        assert audio_part[0]["input_audio"]["format"] == "wav"

    @patch("screenmind.engine.model_manager.is_audio_capable", return_value=False)
    @patch("screenmind.engine.model_manager.get_active_model", return_value="non-audio-model")
    def test_raises_on_non_audio_model(self, _get, _cap):
        """transcribe_audio raises ValueError when model doesn't support audio."""
        with pytest.raises(ValueError, match="does not support audio"):
            transcribe_audio(b"fake wav bytes")

    @patch("screenmind.engine.llm_client.chat")
    @patch("screenmind.engine.model_manager.is_audio_capable", return_value=True)
    def test_strips_unused_tokens(self, _cap, mock_chat):
        """<unusedN> garbage tokens from audio encoder are stripped."""
        mock_chat.return_value = "<unused0><unused1>Hello world<unused99>"
        result = transcribe_audio(b"fake wav bytes")
        assert result == "Hello world"

    @patch("screenmind.engine.llm_client.chat")
    @patch("screenmind.engine.model_manager.is_audio_capable", return_value=True)
    def test_strips_only_unused_tokens(self, _cap, mock_chat):
        """Normal text with angle brackets is preserved."""
        mock_chat.return_value = "The value is <100 and >50"
        result = transcribe_audio(b"fake wav bytes")
        assert result == "The value is <100 and >50"

    @patch("screenmind.engine.llm_client.chat")
    @patch("screenmind.engine.model_manager.is_audio_capable", return_value=True)
    def test_all_unused_returns_empty(self, _cap, mock_chat):
        """If result is entirely garbage tokens, returns empty string."""
        mock_chat.return_value = "<unused0><unused1><unused2>"
        result = transcribe_audio(b"fake wav bytes")
        assert result == ""


class TestGenerate:
    """Tests for generate()."""

    @patch("screenmind.engine.llm_client.chat")
    def test_generate_wraps_as_user_message(self, mock_chat):
        """generate() wraps prompt as a single user message."""
        mock_chat.return_value = "response"
        result = generate("tell me a joke")
        assert result == "response"
        messages = mock_chat.call_args[0][0]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "tell me a joke"


class TestHealthCheck:
    """Tests for is_available() and get_server_status()."""

    @patch("screenmind.engine.llm_client.httpx.get")
    def test_is_available_true(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        assert is_available() is True

    @patch("screenmind.engine.llm_client.httpx.get")
    def test_is_available_false_on_error(self, mock_get):
        mock_get.side_effect = Exception("refused")
        assert is_available() is False

    @patch("screenmind.engine.llm_client.httpx.get")
    def test_get_server_status_ok(self, mock_get):
        mock_resp = MagicMock(status_code=200, text='{"status":"ok"}')
        mock_resp.json.return_value = {"status": "ok"}
        mock_get.return_value = mock_resp
        status = get_server_status()
        assert status["status"] == "ok"

    @patch("screenmind.engine.llm_client.httpx.get")
    def test_get_server_status_unreachable(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("refused")
        status = get_server_status()
        assert status["status"] == "unreachable"

    @patch("screenmind.engine.llm_client.httpx.get")
    def test_get_server_status_http_error(self, mock_get):
        mock_get.return_value = MagicMock(status_code=503)
        status = get_server_status()
        assert status["status"] == "error"
