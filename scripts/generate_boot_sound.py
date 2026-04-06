"""Generate the Axon boot sound as a .wav file.

Replicates the Web Audio API synthesis from ui/js/voice-boot-sound.js:
  1. Servo whir (square wave stepping up, 0–2.5s)
  2. Digital stutter beeps (0.5–3.5s)
  3. Low power hum (sawtooth, 0.3–4.5s)
  4. Reactor core charging tone (triangle, 2.5–5.5s)
  5. "Online" confirmation tone (sine A4, 4.5–6.2s)
  6. Static/digital noise texture (0–3s)

Usage:
    python scripts/generate_boot_sound.py [output_path]
"""
from __future__ import annotations

import math
import struct
import sys

SAMPLE_RATE = 44100
DURATION = 6.5  # seconds
MASTER_GAIN = 0.28


def _lerp(t: float, t0: float, t1: float, v0: float, v1: float) -> float:
    if t1 <= t0:
        return v1
    return v0 + (v1 - v0) * max(0.0, min(1.0, (t - t0) / (t1 - t0)))


def _exp_ramp(t: float, t0: float, t1: float, v0: float, v1: float) -> float:
    if t1 <= t0 or t <= t0:
        return v0
    if t >= t1:
        return v1
    ratio = (t - t0) / (t1 - t0)
    safe_v0 = max(v0, 1e-6)
    safe_v1 = max(v1, 1e-6)
    return safe_v0 * (safe_v1 / safe_v0) ** ratio


def _square(phase: float) -> float:
    return 1.0 if (phase % 1.0) < 0.5 else -1.0


def _sawtooth(phase: float) -> float:
    return 2.0 * (phase % 1.0) - 1.0


def _triangle(phase: float) -> float:
    p = phase % 1.0
    return 4.0 * p - 1.0 if p < 0.5 else 3.0 - 4.0 * p


def _bandpass(samples: list[float], freq: float, q: float, sr: int) -> list[float]:
    w0 = 2.0 * math.pi * freq / sr
    alpha = math.sin(w0) / (2.0 * q)
    b0 = alpha
    b1 = 0.0
    b2 = -alpha
    a0 = 1.0 + alpha
    a1 = -2.0 * math.cos(w0)
    a2 = 1.0 - alpha
    out = [0.0] * len(samples)
    x1 = x2 = y1 = y2 = 0.0
    for i, x in enumerate(samples):
        y = (b0 / a0) * x + (b1 / a0) * x1 + (b2 / a0) * x2 - (a1 / a0) * y1 - (a2 / a0) * y2
        out[i] = y
        x2, x1 = x1, x
        y2, y1 = y1, y
    return out


def _lowpass(samples: list[float], freq: float, q: float, sr: int) -> list[float]:
    w0 = 2.0 * math.pi * freq / sr
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    b0 = (1.0 - cos_w0) / 2.0
    b1 = 1.0 - cos_w0
    b2 = (1.0 - cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    out = [0.0] * len(samples)
    x1 = x2 = y1 = y2 = 0.0
    for i, x in enumerate(samples):
        y = (b0 / a0) * x + (b1 / a0) * x1 + (b2 / a0) * x2 - (a1 / a0) * y1 - (a2 / a0) * y2
        out[i] = y
        x2, x1 = x1, x
        y2, y1 = y1, y
    return out


def _highpass(samples: list[float], freq: float, q: float, sr: int) -> list[float]:
    w0 = 2.0 * math.pi * freq / sr
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    b0 = (1.0 + cos_w0) / 2.0
    b1 = -(1.0 + cos_w0)
    b2 = (1.0 + cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    out = [0.0] * len(samples)
    x1 = x2 = y1 = y2 = 0.0
    for i, x in enumerate(samples):
        y = (b0 / a0) * x + (b1 / a0) * x1 + (b2 / a0) * x2 - (a1 / a0) * y1 - (a2 / a0) * y2
        out[i] = y
        x2, x1 = x1, x
        y2, y1 = y1, y
    return out


def _piecewise_linear(t: float, points: list[tuple[float, float]]) -> float:
    if t <= points[0][0]:
        return points[0][1]
    for i in range(1, len(points)):
        if t <= points[i][0]:
            return _lerp(t, points[i - 1][0], points[i][0], points[i - 1][1], points[i][1])
    return points[-1][1]


def generate() -> list[float]:
    n = int(SAMPLE_RATE * DURATION)
    buf = [0.0] * n

    # ── 1. Servo whir (square wave, 0–2.6s) ──
    servo_raw = [0.0] * n
    freq_steps = [(0.0, 40), (0.4, 55), (0.8, 72), (1.2, 90), (1.6, 110), (2.0, 130)]
    gain_points = [
        (0.0, 0.0), (0.15, 0.06),
        (0.4, 0.08), (0.42, 0.06),
        (0.8, 0.09), (0.82, 0.06),
        (1.2, 0.10), (1.22, 0.06),
        (1.6, 0.10), (1.62, 0.05),
        (2.0, 0.08), (2.5, 0.0),
    ]
    phase = 0.0
    for i in range(min(int(2.6 * SAMPLE_RATE), n)):
        t = i / SAMPLE_RATE
        freq = freq_steps[0][1]
        for j in range(len(freq_steps) - 1, -1, -1):
            if t >= freq_steps[j][0]:
                freq = freq_steps[j][1]
                break
        phase += freq / SAMPLE_RATE
        g = _piecewise_linear(t, gain_points)
        servo_raw[i] = _square(phase) * g
    servo_filtered = _bandpass(servo_raw, 200, 5, SAMPLE_RATE)
    for i in range(len(servo_filtered)):
        buf[i] += servo_filtered[i]

    # ── 2. Digital stutter beeps (0.5–3.5s) ──
    beep_freqs = [220, 330, 275, 440, 350, 550, 440, 660]
    for idx, freq in enumerate(beep_freqs):
        t_start = 0.5 + idx * 0.38
        for i in range(int(0.16 * SAMPLE_RATE)):
            si = int(t_start * SAMPLE_RATE) + i
            if si >= n:
                break
            t_local = i / SAMPLE_RATE
            phase_b = freq * t_local
            # Gain envelope: 0→0.06 in 0.02s, hold, fade to 0 at 0.14s
            if t_local < 0.02:
                g = _lerp(t_local, 0, 0.02, 0, 0.06)
            elif t_local < 0.08:
                g = 0.06
            else:
                g = _lerp(t_local, 0.08, 0.14, 0.06, 0)
            raw_beep = _square(phase_b) * g
            # Simple bandpass approximation
            buf[si] += raw_beep * 0.5

    # ── 3. Low power hum (sawtooth, 0.3–4.8s) ──
    hum_raw = [0.0] * n
    hum_freq_pts = [(0.3, 48), (2.0, 60), (3.5, 72), (4.5, 80)]
    hum_gain_pts = [
        (0.3, 0.0), (1.0, 0.22), (2.5, 0.35), (3.5, 0.40), (4.3, 0.28), (4.8, 0.0),
    ]
    phase = 0.0
    for i in range(int(0.3 * SAMPLE_RATE), min(int(4.9 * SAMPLE_RATE), n)):
        t = i / SAMPLE_RATE
        freq = _piecewise_linear(t, hum_freq_pts)
        phase += freq / SAMPLE_RATE
        g = _piecewise_linear(t, hum_gain_pts)
        hum_raw[i] = _sawtooth(phase) * g
    # Wider lowpass to let bass through
    hum_filtered = _lowpass(hum_raw, 500, 1.5, SAMPLE_RATE)
    for i in range(len(hum_filtered)):
        buf[i] += hum_filtered[i]

    # ── 3b. Sub-bass foundation (sine, 0.5–5.0s) ──
    sub_gain_pts = [
        (0.5, 0.0), (1.2, 0.18), (2.5, 0.28), (3.5, 0.32), (4.5, 0.15), (5.0, 0.0),
    ]
    sub_freq_pts = [(0.5, 32), (2.0, 40), (4.0, 50), (5.0, 55)]
    phase = 0.0
    for i in range(int(0.5 * SAMPLE_RATE), min(int(5.0 * SAMPLE_RATE), n)):
        t = i / SAMPLE_RATE
        freq = _piecewise_linear(t, sub_freq_pts)
        phase += freq / SAMPLE_RATE
        g = _piecewise_linear(t, sub_gain_pts)
        buf[i] += math.sin(2.0 * math.pi * phase) * g

    # ── 4. Reactor core charging tone (triangle, 2.5–5.8s) ──
    core_raw = [0.0] * n
    core_freq_pts = [(2.5, 80), (3.5, 140), (4.5, 200), (5.5, 220)]
    core_gain_pts = [
        (2.5, 0.0), (3.0, 0.16), (4.0, 0.26), (5.0, 0.30), (5.4, 0.14), (5.8, 0.0),
    ]
    phase = 0.0
    for i in range(int(2.5 * SAMPLE_RATE), min(int(5.9 * SAMPLE_RATE), n)):
        t = i / SAMPLE_RATE
        freq = _piecewise_linear(t, core_freq_pts)
        phase += freq / SAMPLE_RATE
        g = _piecewise_linear(t, core_gain_pts)
        core_raw[i] = _triangle(phase) * g
    core_filtered = _bandpass(core_raw, 300, 2, SAMPLE_RATE)
    for i in range(len(core_filtered)):
        buf[i] += core_filtered[i]

    # ── 5. "Online" confirmation tone (sine A4, 4.5–6.2s) ──
    ready_gain_pts = [
        (4.5, 0.0), (4.65, 0.14), (5.2, 0.12),
    ]
    for i in range(int(4.5 * SAMPLE_RATE), min(int(6.3 * SAMPLE_RATE), n)):
        t = i / SAMPLE_RATE
        if t <= 5.2:
            g = _piecewise_linear(t, ready_gain_pts)
        else:
            g = _exp_ramp(t, 5.2, 6.2, 0.12, 0.01)
        buf[i] += math.sin(2.0 * math.pi * 440 * t) * g

    # ── 6. Static/digital noise texture (0–3s) ──
    import random
    rng = random.Random(42)
    noise_raw = [0.0] * n
    noise_gain_pts = [(0.0, 0.03), (0.8, 0.05), (1.5, 0.04)]
    for i in range(min(int(3.0 * SAMPLE_RATE), n)):
        t = i / SAMPLE_RATE
        if t <= 1.5:
            g = _piecewise_linear(t, noise_gain_pts)
        else:
            g = _exp_ramp(t, 1.5, 3.0, 0.04, 0.005)
        noise_raw[i] = round((rng.random() * 2 - 1) * 4) / 4 * 0.3 * g
    noise_filtered = _highpass(noise_raw, 2000, 0.5, SAMPLE_RATE)
    for i in range(len(noise_filtered)):
        buf[i] += noise_filtered[i]

    # ── Master envelope ──
    master_pts = [(0.0, 0.28), (5.5, 0.28), (6.5, 0.0)]
    for i in range(n):
        t = i / SAMPLE_RATE
        buf[i] *= _piecewise_linear(t, master_pts)

    return buf


def write_wav(path: str, samples: list[float], sr: int = SAMPLE_RATE) -> None:
    n = len(samples)
    data_size = n * 2  # 16-bit mono
    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # chunk size
        f.write(struct.pack("<H", 1))  # PCM
        f.write(struct.pack("<H", 1))  # mono
        f.write(struct.pack("<I", sr))  # sample rate
        f.write(struct.pack("<I", sr * 2))  # byte rate
        f.write(struct.pack("<H", 2))  # block align
        f.write(struct.pack("<H", 16))  # bits per sample
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        for s in samples:
            clamped = max(-1.0, min(1.0, s))
            f.write(struct.pack("<h", int(clamped * 32767)))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "axon-boot-sound.wav"
    print(f"Generating boot sound → {out}")
    samples = generate()
    write_wav(out, samples)
    print(f"Done. {len(samples)} samples, {len(samples) / SAMPLE_RATE:.1f}s")
