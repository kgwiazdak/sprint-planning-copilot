from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from backend.infrastructure.transcription.azure_conversation import AzureConversationTranscriber


class TestAzureConversationTranscriberInit:
    """Tests for AzureConversationTranscriber initialization."""

    def test_raises_value_error_when_key_is_missing(self):
        with pytest.raises(ValueError, match="Azure Speech key and region must be configured"):
            AzureConversationTranscriber(key=None, region="eastus")

    def test_raises_value_error_when_region_is_missing(self):
        with pytest.raises(ValueError, match="Azure Speech key and region must be configured"):
            AzureConversationTranscriber(key="test-key", region=None)

    def test_raises_value_error_when_both_key_and_region_missing(self):
        with pytest.raises(ValueError, match="Azure Speech key and region must be configured"):
            AzureConversationTranscriber(key=None, region=None)

    def test_default_timeout_values(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk"):
            transcriber = AzureConversationTranscriber(key="test-key", region="eastus")
            assert transcriber._transcription_timeout == AzureConversationTranscriber.DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS
            assert transcriber._stop_timeout == AzureConversationTranscriber.DEFAULT_STOP_TIMEOUT_SECONDS

    def test_custom_timeout_values(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk"):
            transcriber = AzureConversationTranscriber(
                key="test-key",
                region="eastus",
                transcription_timeout=120,
                stop_timeout=5,
            )
            assert transcriber._transcription_timeout == 120
            assert transcriber._stop_timeout == 5

    def test_timeout_from_environment_variables(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk"):
            with patch.dict("os.environ", {
                "TRANSCRIPTION_TIMEOUT_SECONDS": "300",
                "TRANSCRIPTION_STOP_TIMEOUT_SECONDS": "15"
            }):
                transcriber = AzureConversationTranscriber(key="test-key", region="eastus")
                assert transcriber._transcription_timeout == 300
                assert transcriber._stop_timeout == 15


class TestAzureConversationTranscriberRoleFromFilename:
    """Tests for the _role_from_filename static method."""

    def test_role_from_simple_filename(self):
        from pathlib import Path
        result = AzureConversationTranscriber._role_from_filename(Path("intro_john.wav"))
        assert result == "John"

    def test_role_from_filename_with_underscores(self):
        from pathlib import Path
        result = AzureConversationTranscriber._role_from_filename(Path("intro_john_doe.wav"))
        assert result == "John Doe"

    def test_role_from_filename_with_hyphen(self):
        from pathlib import Path
        result = AzureConversationTranscriber._role_from_filename(Path("intro_mary-jane.wav"))
        assert result == "Mary-Jane"

    def test_role_from_filename_empty_returns_speaker(self):
        from pathlib import Path
        result = AzureConversationTranscriber._role_from_filename(Path("intro_.wav"))
        assert result == "Speaker"


class TestAzureConversationTranscriberCleanup:
    """Tests for the _cleanup_transcriber method."""

    def test_cleanup_disconnects_all_handlers(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk"):
            transcriber = AzureConversationTranscriber(key="test-key", region="eastus")

            mock_conversation_transcriber = MagicMock()
            mock_conversation_transcriber.stop_transcribing_async.return_value.get.return_value = None
            done_event = threading.Event()
            done_event.set()

            transcriber._cleanup_transcriber(mock_conversation_transcriber, started=True, done=done_event)

            mock_conversation_transcriber.stop_transcribing_async.assert_called_once()
            mock_conversation_transcriber.transcribed.disconnect_all.assert_called_once()
            mock_conversation_transcriber.canceled.disconnect_all.assert_called_once()
            mock_conversation_transcriber.session_stopped.disconnect_all.assert_called_once()

    def test_cleanup_handles_stop_timeout_gracefully(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk"):
            transcriber = AzureConversationTranscriber(key="test-key", region="eastus", stop_timeout=1)

            mock_conversation_transcriber = MagicMock()
            mock_conversation_transcriber.stop_transcribing_async.return_value.get.side_effect = TimeoutError(
                "Timeout while waiting for service to stop"
            )
            done_event = threading.Event()

            # Should not raise - cleanup should swallow exceptions
            transcriber._cleanup_transcriber(mock_conversation_transcriber, started=True, done=done_event)

            # Disconnect should still be called despite timeout
            mock_conversation_transcriber.transcribed.disconnect_all.assert_called_once()

    def test_cleanup_skips_stop_if_not_started(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk"):
            transcriber = AzureConversationTranscriber(key="test-key", region="eastus")

            mock_conversation_transcriber = MagicMock()
            done_event = threading.Event()

            transcriber._cleanup_transcriber(mock_conversation_transcriber, started=False, done=done_event)

            mock_conversation_transcriber.stop_transcribing_async.assert_not_called()
            # Disconnect should still be called
            mock_conversation_transcriber.transcribed.disconnect_all.assert_called_once()

    def test_cleanup_handles_disconnect_exception(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk"):
            transcriber = AzureConversationTranscriber(key="test-key", region="eastus")

            mock_conversation_transcriber = MagicMock()
            mock_conversation_transcriber.stop_transcribing_async.return_value.get.return_value = None
            mock_conversation_transcriber.transcribed.disconnect_all.side_effect = RuntimeError("disconnect failed")
            done_event = threading.Event()
            done_event.set()

            # Should not raise - cleanup should swallow exceptions
            transcriber._cleanup_transcriber(mock_conversation_transcriber, started=True, done=done_event)

            # Other disconnects should still be attempted
            mock_conversation_transcriber.canceled.disconnect_all.assert_called_once()
            mock_conversation_transcriber.session_stopped.disconnect_all.assert_called_once()


class TestAzureConversationTranscriberTranscribe:
    """Tests for the transcribe method."""

    def test_transcribe_rejects_unsupported_format(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk"):
            transcriber = AzureConversationTranscriber(key="test-key", region="eastus")
            with pytest.raises(ValueError, match="Unsupported audio format"):
                transcriber.transcribe(b"fake audio content", "meeting.txt")

    def test_transcribe_accepts_wav_format(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk") as mock_sdk:
            with patch("backend.infrastructure.transcription.azure_conversation.normalizer") as mock_normalizer:
                with patch("backend.infrastructure.transcription.azure_conversation.speech_transcription") as mock_speech:
                    # Set up mocks
                    mock_normalizer.convert_to_standard_wav.return_value = b"RIFF" + b"\x00" * 40
                    mock_normalizer.wav_payload.return_value = (b"frames", 100, 16000, 2, 1)
                    mock_normalizer.build_wav.return_value = b"RIFF" + b"\x00" * 40
                    mock_normalizer.frames_to_ticks.return_value = 0

                    mock_transcriber_instance = MagicMock()
                    mock_speech.ConversationTranscriber.return_value = mock_transcriber_instance

                    # Simulate immediate completion via session_stopped
                    def simulate_transcription(*args, **kwargs):
                        # Get the handlers that were connected
                        stopped_handler = mock_transcriber_instance.session_stopped.connect.call_args[0][0]
                        # Simulate the session stopped event
                        stopped_handler(MagicMock())
                        return MagicMock()

                    mock_transcriber_instance.start_transcribing_async.return_value.get.side_effect = simulate_transcription

                    transcriber = AzureConversationTranscriber(key="test-key", region="eastus")

                    # This should raise because no speech recognized, but not timeout
                    with pytest.raises(RuntimeError, match="No speech could be recognized"):
                        transcriber.transcribe(b"wav content", "meeting.wav")

    def test_transcribe_accepts_mp3_format(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk") as mock_sdk:
            with patch("backend.infrastructure.transcription.azure_conversation.normalizer") as mock_normalizer:
                with patch("backend.infrastructure.transcription.azure_conversation.speech_transcription") as mock_speech:
                    mock_normalizer.convert_to_standard_wav.return_value = b"RIFF" + b"\x00" * 40
                    mock_normalizer.wav_payload.return_value = (b"frames", 100, 16000, 2, 1)
                    mock_normalizer.build_wav.return_value = b"RIFF" + b"\x00" * 40
                    mock_normalizer.frames_to_ticks.return_value = 0

                    mock_transcriber_instance = MagicMock()
                    mock_speech.ConversationTranscriber.return_value = mock_transcriber_instance

                    def simulate_transcription(*args, **kwargs):
                        stopped_handler = mock_transcriber_instance.session_stopped.connect.call_args[0][0]
                        stopped_handler(MagicMock())
                        return MagicMock()

                    mock_transcriber_instance.start_transcribing_async.return_value.get.side_effect = simulate_transcription

                    transcriber = AzureConversationTranscriber(key="test-key", region="eastus")

                    with pytest.raises(RuntimeError, match="No speech could be recognized"):
                        transcriber.transcribe(b"mp3 content", "meeting.mp3")

    def test_transcribe_timeout_raises_informative_error(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk") as mock_sdk:
            with patch("backend.infrastructure.transcription.azure_conversation.normalizer") as mock_normalizer:
                with patch("backend.infrastructure.transcription.azure_conversation.speech_transcription") as mock_speech:
                    mock_normalizer.convert_to_standard_wav.return_value = b"RIFF" + b"\x00" * 40
                    mock_normalizer.wav_payload.return_value = (b"frames", 100, 16000, 2, 1)
                    mock_normalizer.build_wav.return_value = b"RIFF" + b"\x00" * 40
                    mock_normalizer.frames_to_ticks.return_value = 0

                    mock_transcriber_instance = MagicMock()
                    mock_speech.ConversationTranscriber.return_value = mock_transcriber_instance

                    # Don't trigger any completion event - let it timeout
                    mock_transcriber_instance.start_transcribing_async.return_value.get.return_value = None

                    # Use a very short timeout for testing
                    transcriber = AzureConversationTranscriber(
                        key="test-key",
                        region="eastus",
                        transcription_timeout=0,  # Immediate timeout
                        stop_timeout=0,
                    )

                    with pytest.raises(RuntimeError, match="Transcription timed out after 0 seconds"):
                        transcriber.transcribe(b"wav content", "meeting.wav")

    def test_transcribe_cancellation_error_is_raised(self):
        with patch("backend.infrastructure.transcription.azure_conversation.speechsdk") as mock_sdk:
            with patch("backend.infrastructure.transcription.azure_conversation.normalizer") as mock_normalizer:
                with patch("backend.infrastructure.transcription.azure_conversation.speech_transcription") as mock_speech:
                    mock_normalizer.convert_to_standard_wav.return_value = b"RIFF" + b"\x00" * 40
                    mock_normalizer.wav_payload.return_value = (b"frames", 100, 16000, 2, 1)
                    mock_normalizer.build_wav.return_value = b"RIFF" + b"\x00" * 40
                    mock_normalizer.frames_to_ticks.return_value = 0

                    mock_transcriber_instance = MagicMock()
                    mock_speech.ConversationTranscriber.return_value = mock_transcriber_instance

                    # Simulate cancellation error
                    def simulate_cancellation(*args, **kwargs):
                        canceled_handler = mock_transcriber_instance.canceled.connect.call_args[0][0]
                        mock_event = MagicMock()
                        mock_event.result.cancellation_details.reason = mock_sdk.CancellationReason.Error
                        mock_event.result.cancellation_details.error_details = "Network error occurred"
                        canceled_handler(mock_event)
                        return MagicMock()

                    mock_transcriber_instance.start_transcribing_async.return_value.get.side_effect = simulate_cancellation

                    transcriber = AzureConversationTranscriber(key="test-key", region="eastus")

                    with pytest.raises(RuntimeError, match="Conversation transcription canceled"):
                        transcriber.transcribe(b"wav content", "meeting.wav")


class TestBackwardsCompatibility:
    """Tests for backwards compatibility aliases."""

    def test_transcriber_alias_exists(self):
        from backend.infrastructure.transcription.azure_conversation import Transcriber
        assert Transcriber is AzureConversationTranscriber

    def test_supported_extensions_alias_exists(self):
        from backend.infrastructure.transcription.azure_conversation import SUPPORTED_AUDIO_EXTENSIONS
        assert SUPPORTED_AUDIO_EXTENSIONS == AzureConversationTranscriber.SUPPORTED_AUDIO_EXTENSIONS
