"""MP3 telecast audio (task 9.4)."""

import math
import struct
import wave
from pathlib import Path

import pytest

from app.press.audio import AudioEncodeError, encode_mp3, lead_ms
from app.press.telecast import to_mp3


def tone_wav(path: Path, seconds: float = 2.0, rate: int = 24000) -> Path:
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(int(seconds * rate))
    )
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


def test_encode_mp3_is_about_six_times_smaller(tmp_path: Path) -> None:
    wav = tone_wav(tmp_path / "a.wav")
    size = encode_mp3(wav, tmp_path / "a.mp3")
    data = (tmp_path / "a.mp3").read_bytes()
    assert size == len(data)
    assert data[0] == 0xFF and data[1] & 0xE0 == 0xE0  # MPEG audio frame sync
    assert wav.stat().st_size / size > 5
    assert not (tmp_path / "a.mp3.part").exists()


def test_encode_rejects_what_is_not_a_pcm16_wav(tmp_path: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav")
    with pytest.raises(AudioEncodeError):
        encode_mp3(bad, tmp_path / "bad.mp3")
    with pytest.raises(AudioEncodeError):
        encode_mp3(tmp_path / "missing.wav", tmp_path / "missing.mp3")


def test_to_mp3_replaces_the_wav_or_keeps_it_on_failure(tmp_path: Path) -> None:
    wav = tone_wav(tmp_path / "t.wav", seconds=0.5)
    assert to_mp3(wav, "telecasts/t.wav") == "telecasts/t.mp3"
    assert not wav.exists() and (tmp_path / "t.mp3").is_file()
    broken = tmp_path / "b.wav"
    broken.write_bytes(b"x")
    assert to_mp3(broken, "telecasts/b.wav") == "telecasts/b.wav"
    assert broken.exists()


def test_lead_ms_only_for_mp3() -> None:
    assert lead_ms("telecasts/a.mp3", 24000) == 46
    assert lead_ms("telecasts/a.wav", 24000) == 0
    assert lead_ms(None, 24000) == 0
