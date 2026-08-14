"""
Task 3 — audio feature extraction.

For every submitted audio file (recorded in-browser via st.audio_input, or
uploaded as any common format), we need to auto-extract: duration, sample
rate (kHz), bitrate, and loudness (dB), plus a bonus rough noise/quality
estimate.

Design decisions worth being able to explain (see also context.md / README):

- We use pydub (backed by ffmpeg) instead of trying to hand-roll format
  parsing. ffmpeg can decode virtually any format thrown at it, so this
  works uniformly whether the input is the WAV that st.audio_input always
  produces, or an uploaded mp3/m4a/ogg/flac file.

- "Bitrate" is ambiguous for audio in general - an mp3 has a nominal encoded
  bitrate baked into its header, but a decoded WAV doesn't have one in the
  same sense (it's just raw samples). Rather than depend on format-specific
  metadata parsing (which would need a separate library like mutagen and
  would give inconsistent answers across formats), we compute an EFFECTIVE
  bitrate = (file size in bits) / duration. This is a defensible, uniform
  answer to "how many bits per second does this file actually occupy" that
  works the same way regardless of input format. Worth flagging as a
  deliberate simplification if asked about it.

- "Loudness (dB)" is reported as dBFS (decibels relative to full scale) via
  pydub's built-in .dBFS property - the standard way to express loudness for
  digital audio without needing a perceptual loudness model (like LUFS,
  which is more involved to compute correctly). Silence produces -inf dBFS,
  which we explicitly detect and report as None with a "silent" flag rather
  than storing a non-finite number in SQLite.

- The noise/quality estimate (bonus) is a deliberately simple, explainable
  heuristic, not a proper acoustic SNR measurement: we compute short-time
  RMS energy in ~50ms frames, treat the 10th percentile as an approximate
  noise floor and the 90th percentile as an approximate signal level, and
  express their ratio in dB as an approximate SNR. This is a reasonable
  proxy - louder/cleaner speech has a bigger gap between its quiet and loud
  moments than a noisy recording does - but it is NOT a substitute for a
  real perceptual noise model. That tradeoff (simple & explainable vs.
  accurate) is intentional and worth being upfront about.

  CAUGHT DURING TESTING: this heuristic only works when the signal has
  natural quiet/loud variation over time, the way real speech does (pauses
  between words). Tested first against a constant pure tone and got a
  meaningless ~0dB "noisy" result even for a perfectly clean tone - a
  constant signal has no quiet moments to measure a noise floor from, so
  its 10th/90th percentile RMS are nearly identical regardless of actual
  noise. Re-tested against a more realistic synthetic signal (tone bursts
  separated by silence gaps, i.e. actually shaped like speech) and it
  differentiated correctly: clean ~170dB, moderate background noise ~10dB,
  heavy noise ~2dB. Also added an explicit near-silence guard, since
  dividing two near-zero percentiles is mathematically meaningless, not a
  real "noisy" reading - it now reports "Silent" instead.
"""
import math
from pydub import AudioSegment
import numpy as np


def analyze_audio(file_bytes: bytes, filename_hint: str = "audio.wav") -> dict:
    """
    Takes raw audio bytes (from st.audio_input or st.file_uploader) and
    returns a dict of extracted properties. Raises a clear exception if the
    file can't be decoded at all, so the caller can show a friendly error
    instead of a stack trace.
    """
    import io
    import os

    ext = os.path.splitext(filename_hint)[1].lstrip(".").lower() or "wav"
    try:
        seg = AudioSegment.from_file(io.BytesIO(file_bytes), format=ext)
    except Exception:
        # format hint was wrong or missing - let ffmpeg auto-detect instead
        seg = AudioSegment.from_file(io.BytesIO(file_bytes))

    duration_sec = len(seg) / 1000.0
    sample_rate_hz = seg.frame_rate
    channels = seg.channels
    sample_width_bytes = seg.sample_width  # bytes per sample, e.g. 2 for 16-bit

    file_size_bytes = len(file_bytes)
    bitrate_kbps = round((file_size_bytes * 8) / duration_sec / 1000, 1) if duration_sec > 0 else None

    loudness_dbfs = seg.dBFS
    is_silent = math.isinf(loudness_dbfs) or math.isnan(loudness_dbfs)
    loudness_db = None if is_silent else round(loudness_dbfs, 1)

    noise_estimate = _estimate_noise(seg, sample_rate_hz, channels, sample_width_bytes)

    return dict(
        duration_sec=round(duration_sec, 2),
        sample_rate_hz=sample_rate_hz,
        sample_rate_khz=round(sample_rate_hz / 1000, 1),
        channels=channels,
        bitrate_kbps=bitrate_kbps,
        loudness_db=loudness_db,
        is_silent=is_silent,
        noise_estimate=noise_estimate,
    )


def _estimate_noise(seg, sample_rate_hz, channels, sample_width_bytes) -> str:
    """Bonus: rough noise/quality estimate via short-time RMS envelope. See
    module docstring above for why this heuristic and not something fancier."""
    try:
        samples = np.array(seg.get_array_of_samples()).astype(np.float64)
        if channels > 1:
            samples = samples.reshape((-1, channels)).mean(axis=1)  # downmix to mono

        max_val = float(2 ** (8 * sample_width_bytes - 1))
        normalized = samples / max_val  # scale to [-1, 1]

        # Guard against true/near silence: percentile ratios of near-zero
        # values are mathematically meaningless (e.g. 0/epsilon), not a real
        # SNR reading. Caught during testing - see stuck log.
        overall_rms = np.sqrt(np.mean(normalized ** 2))
        if overall_rms < 1e-4:
            return "Silent - no audio energy detected"

        frame_len = max(int(sample_rate_hz * 0.05), 1)  # ~50ms frames
        n_frames = len(normalized) // frame_len
        if n_frames < 4:
            return "Too short to estimate"

        frames = normalized[: n_frames * frame_len].reshape(n_frames, frame_len)
        rms_per_frame = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9

        noise_floor = np.percentile(rms_per_frame, 10)
        signal_level = np.percentile(rms_per_frame, 90)
        snr_db = 20 * np.log10(signal_level / (noise_floor + 1e-12))
        snr_db = min(snr_db, 60.0)  # cap - beyond ~60dB the number stops being meaningful, just says "very clean"

        if snr_db > 30:
            label = "Clean"
        elif snr_db > 15:
            label = "Some background noise"
        else:
            label = "Noisy / low quality"
        return f"{label} (approx SNR {snr_db:.1f} dB)"
    except Exception as e:
        return f"Could not estimate ({e})"
