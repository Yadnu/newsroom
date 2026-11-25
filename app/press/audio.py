"""Telecast audio as MP3 (task 9.4, decision 0029).

The Anchor writes PCM16 WAV; ``encode_mp3`` makes mono CBR MP3 with LAME (``lameenc``), about six
times smaller at 64 kbps. lameenc writes no Xing/Info header, so browsers keep the LAME encoder
delay plus the decoder's: ``MP3_DELAY_SAMPLES`` (about 46 ms at 24 kHz) of silence comes first,
reported to the player as ``audio_lead_ms`` so captions and lip sync stay aligned.
"""

import wave
from pathlib import Path

import lameenc

MP3_BITRATE_KBPS = 64
MP3_DELAY_SAMPLES = 576 + 529  # LAME encoder delay + MP3 decoder delay
CHUNK_FRAMES = 24_000


class AudioEncodeError(RuntimeError):
    pass


def lead_ms(audio_path: str | None, sample_rate: int) -> int:
    """Silence the player must skip at the start of a telecast's audio file (0 for WAV)."""
    if audio_path and audio_path.endswith(".mp3"):
        return round(MP3_DELAY_SAMPLES * 1000 / sample_rate)
    return 0


def encode_mp3(wav_path: Path, mp3_path: Path, bitrate_kbps: int = MP3_BITRATE_KBPS) -> int:
    """Encode a mono PCM16 WAV to MP3. Returns the MP3 size in bytes. Raises AudioEncodeError."""
    try:
        with wave.open(str(wav_path), "rb") as w:
            if w.getsampwidth() != 2:
                raise AudioEncodeError(f"{wav_path.name}: expected 16-bit PCM")
            enc = lameenc.Encoder()
            enc.set_bit_rate(bitrate_kbps)
            enc.set_in_sample_rate(w.getframerate())
            enc.set_channels(w.getnchannels())
            enc.set_quality(2)  # 2 = high quality, 7 = fast
            tmp = mp3_path.with_suffix(".mp3.part")
            with tmp.open("wb") as out:
                while frames := w.readframes(CHUNK_FRAMES):
                    out.write(enc.encode(frames))
                out.write(enc.flush())
    except (OSError, EOFError, wave.Error, RuntimeError) as e:
        if isinstance(e, AudioEncodeError):
            raise
        raise AudioEncodeError(f"{wav_path.name}: {type(e).__name__}: {e}") from e
    tmp.replace(mp3_path)
    return mp3_path.stat().st_size
