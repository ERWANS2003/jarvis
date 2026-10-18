"""Tests du VAD et de l'endpointing (Horizon 5)."""

from __future__ import annotations

import array

from jarvis_core import vad as V

FRAME_FRAMES = 480  # 30 ms a 16 kHz


def _frame(value: int) -> bytes:
    return array.array("h", [value] * FRAME_FRAMES).tobytes()


SILENT = _frame(0)
QUIET = _frame(120)
LOUD = _frame(12000)


def test_config_geometry():
    cfg = V.VADConfig()
    assert cfg.sample_rate == 16000
    assert cfg.frame_frames == 480
    assert cfg.frame_bytes == 960


def test_energy_vad_calibrates_and_detects():
    detector = V.EnergyVAD()
    floor = detector.calibrate([QUIET] * 10)
    assert floor == 120.0
    # seuil = max(120*1.8, 350) = 350
    assert detector.threshold() == 350.0
    assert detector.is_speech(LOUD) is True
    assert detector.is_speech(SILENT) is False
    assert detector.is_speech(QUIET) is False


def test_energy_vad_noise_floor_raises_threshold():
    detector = V.EnergyVAD()
    detector.calibrate([_frame(5000)] * 10)
    assert detector.threshold() > 5000


def test_make_vad_returns_energy_when_webrtc_absent():
    detector = V.make_vad()
    assert isinstance(detector, V.EnergyVAD)


def _scripted(frames: list[bytes]):
    queue = list(frames)

    def reader(n_frames: int) -> bytes:
        return queue.pop(0) if queue else b""

    return reader


def test_recorder_captures_speech():
    script = [SILENT] * 5 + [LOUD] * 6 + [SILENT] * 5
    cfg = V.VADConfig(frame_ms=30, silence_ms=90, min_speech_ms=60,
                      start_timeout_ms=1000, max_speech_ms=5000, pre_roll_ms=60)
    detector = V.EnergyVAD()
    detector.calibrate([SILENT] * 5)
    recorder = V.VADRecorder(stream=None, config=cfg, detector=detector,
                             frames_reader=_scripted(script))
    result = recorder.record()
    assert result is not None
    assert result.speech_ms >= 180
    # 2 frames de pre-roll + 6 frames de voix + 3 frames de silence final
    assert len(result.pcm) == 11 * cfg.frame_bytes


def test_recorder_returns_none_on_silence():
    cfg = V.VADConfig(frame_ms=30, start_timeout_ms=150, silence_ms=90)
    detector = V.EnergyVAD()
    recorder = V.VADRecorder(stream=None, config=cfg, detector=detector,
                             frames_reader=_scripted([SILENT] * 50))
    assert recorder.record() is None


def test_recorder_returns_none_on_too_short_burst():
    cfg = V.VADConfig(frame_ms=30, silence_ms=90, min_speech_ms=300,
                      start_timeout_ms=1000, max_speech_ms=2000, pre_roll_ms=30)
    detector = V.EnergyVAD()
    detector.calibrate([SILENT] * 5)
    script = [SILENT] * 2 + [LOUD] + [SILENT] * 20
    recorder = V.VADRecorder(stream=None, config=cfg, detector=detector,
                             frames_reader=_scripted(script))
    assert recorder.record() is None


def test_recorder_stops_at_max_speech():
    cfg = V.VADConfig(frame_ms=30, silence_ms=90, min_speech_ms=60,
                      start_timeout_ms=1000, max_speech_ms=300, pre_roll_ms=30)
    detector = V.EnergyVAD()
    detector.calibrate([SILENT] * 5)
    recorder = V.VADRecorder(stream=None, config=cfg, detector=detector,
                             frames_reader=_scripted([SILENT] * 3 + [LOUD] * 100))
    result = recorder.record()
    assert result is not None
    assert result.total_ms <= 300 + cfg.frame_ms


def test_trim_silence():
    pcm = SILENT * 3 + LOUD * 4 + SILENT * 3
    trimmed = V.trim_silence(pcm, frame_ms=30, threshold=350.0)
    assert len(trimmed) == 4 * FRAME_FRAMES * 2


def test_pcm_to_audio_data():
    audio = V.pcm_to_audio_data(LOUD * 2)
    assert audio.sample_rate == 16000
    assert audio.sample_width == 2
    assert len(audio.get_raw_data()) == len(LOUD) * 2
