"""
Tests for app/audio_utils.py.

These exist because the noise-estimate heuristic looked correct on paper but
gave meaningless results against the first (naive) test case - see the
docstring in audio_utils.py and the README stuck log for the full story.
Keeping these as real, runnable tests (not just throwaway scratch commands)
so the fix stays verified if the heuristic is ever touched again.

Run with: python3 -m pytest tests/test_audio_utils.py -v
"""
import io
import sys
from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
from audio_utils import analyze_audio

SR = 16000


def _make_wav_bytes(signal, sample_rate=SR):
    signal = np.clip(signal, -1, 1)
    signal_int16 = (signal * 32767).astype(np.int16)
    seg = AudioSegment(signal_int16.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)
    buf = io.BytesIO()
    seg.export(buf, format="wav")
    return buf.getvalue()


def _speech_like_signal(duration_sec=4, seed=None, noise_amplitude=0.0):
    """Tone bursts separated by silence gaps - structured like real speech
    (as opposed to a continuous tone, which has no quiet/loud variation and
    is NOT representative of voice - see stuck log entry)."""
    t = np.linspace(0, duration_sec, SR * duration_sec, endpoint=False)
    burst_pattern = (np.sin(2 * np.pi * 3 * t) > 0.3).astype(float)
    signal = 0.6 * np.sin(2 * np.pi * 220 * t) * burst_pattern
    if noise_amplitude:
        rng = np.random.default_rng(seed)
        signal = signal + noise_amplitude * rng.normal(0, 1, len(t))
    return signal


def test_duration_and_sample_rate():
    signal = _speech_like_signal(duration_sec=3)
    result = analyze_audio(_make_wav_bytes(signal), "test.wav")
    assert result["duration_sec"] == pytest.approx(3.0, abs=0.05)
    assert result["sample_rate_hz"] == SR
    assert result["sample_rate_khz"] == SR / 1000


def test_silence_reports_none_loudness_not_negative_infinity():
    silence = np.zeros(SR * 2)
    result = analyze_audio(_make_wav_bytes(silence), "test.wav")
    assert result["is_silent"] is True
    assert result["loudness_db"] is None  # not -inf - must be JSON/SQLite safe
    assert "Silent" in result["noise_estimate"]


def test_noise_estimate_is_monotonic_with_added_noise():
    """The core regression test for the bug: noise estimate must actually
    decrease (in dB) as more noise is added. A naive implementation that
    only worked 'in theory' failed this against a continuous-tone test case
    first - this uses a speech-shaped signal instead, which is what the
    heuristic is designed for."""
    clean = analyze_audio(_make_wav_bytes(_speech_like_signal(noise_amplitude=0.0)), "test.wav")
    moderate = analyze_audio(_make_wav_bytes(_speech_like_signal(seed=1, noise_amplitude=0.15)), "test.wav")
    heavy = analyze_audio(_make_wav_bytes(_speech_like_signal(seed=1, noise_amplitude=0.5)), "test.wav")

    def snr_value(result):
        # extract the numeric dB value from strings like "Clean (approx SNR 60.0 dB)"
        return float(result["noise_estimate"].split("SNR ")[1].split(" dB")[0])

    assert snr_value(clean) > snr_value(moderate) > snr_value(heavy)
    assert "Clean" in clean["noise_estimate"]
    assert "Noisy" in heavy["noise_estimate"]


def test_continuous_tone_does_not_crash_even_though_heuristic_is_weak_here():
    """Known limitation, documented rather than hidden: a continuous tone has
    no quiet/loud variation, so the noise estimate isn't meaningful for it.
    It must still run without error and return some string, not raise."""
    t = np.linspace(0, 2, SR * 2, endpoint=False)
    tone = 0.5 * np.sin(2 * np.pi * 440 * t)
    result = analyze_audio(_make_wav_bytes(tone), "test.wav")
    assert isinstance(result["noise_estimate"], str)


def test_mp3_bitrate_is_close_to_encoded_bitrate():
    """Sanity check for the 'effective bitrate = filesize/duration' design
    decision: it should land close to (not necessarily exact) the real
    encoded bitrate for a compressed file, not wildly off."""
    wav_bytes = _make_wav_bytes(_speech_like_signal(duration_sec=4))
    buf = io.BytesIO()
    AudioSegment.from_file(io.BytesIO(wav_bytes)).export(buf, format="mp3", bitrate="128k")
    result = analyze_audio(buf.getvalue(), "test.mp3")
    assert 100 < result["bitrate_kbps"] < 160  # near 128k, generous tolerance for mp3 container overhead


if __name__ == "__main__":
    import subprocess
    subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"])
