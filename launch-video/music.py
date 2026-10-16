"""Original soundtrack for the launch video, synthesized from scratch (no samples, no licensing).
Cues are timed to the scene windows in index.html.  Usage: python music.py out.wav"""
import sys
import wave

import numpy as np

SR = 48000
DUR = 45.0
N = int(SR * DUR)
rng = np.random.default_rng(7)
BPM = 112
BEAT = 60 / BPM
L = np.zeros(N)
R = np.zeros(N)


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def place(sig, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= N:
        return
    sig = sig[: N - i]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    L[i:i + len(sig)] += sig * gain * l * 1.41
    R[i:i + len(sig)] += sig * gain * r * 1.41


def env(n, a=0.01, d=0.2, s=0.0, rel=0.1, hold=None):
    t = np.arange(n) / SR
    hold = hold if hold is not None else n / SR - rel
    e = np.where(t < a, t / max(a, 1e-6), 1.0)
    dec = s + (1 - s) * np.exp(-(t - a) / max(d, 1e-6))
    e = np.where(t >= a, dec, e)
    e = np.where(t > hold, e * np.exp(-(t - hold) / max(rel, 1e-6) * 3), e)
    return e


def saw_pad(freq, dur, bright=10.0, voices=(-7, 0, 6)):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for cents in voices:
        f = freq * 2 ** (cents / 1200)
        phase = rng.uniform(0, 2 * np.pi)
        for h in range(1, 24):
            if f * h > 9000:
                break
            out += np.sin(2 * np.pi * f * h * t + phase * h) / h * np.exp(-h / bright)
    return out / len(voices)


def pad_chord(notes, t0, dur, gain=0.05, bright=6.0):
    n = int(dur * SR)
    e = env(n, a=min(1.2, dur / 3), d=10, s=1.0, rel=0.9)
    for k, note in enumerate(notes):
        place(saw_pad(midi(note), dur, bright) * e, t0, gain, pan=(-0.5 + k / max(1, len(notes) - 1)) * 0.8)


def kick(t, g=0.9):
    n = int(0.45 * SR)
    tt = np.arange(n) / SR
    f = 45 + 95 * np.exp(-tt * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-tt * 7.5) + 0.25 * rng.standard_normal(n) * np.exp(-tt * 300)
    place(s, t, g)


def hat(t, g=0.12, dec=55, pan=0.25):
    n = int(0.12 * SR)
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=0)
    place(hp * np.exp(-np.arange(n) / SR * dec), t, g, pan)


def clap(t, g=0.28):
    n = int(0.3 * SR)
    noise = rng.standard_normal(n)
    bp = np.diff(noise, prepend=0) * 0.6 + noise * 0.4
    e = np.exp(-np.arange(n) / SR * 16)
    for k, dt in enumerate((0, 0.012, 0.024)):
        place(bp * e * (0.6 if k else 1), t + dt, g / 2, pan=(-0.2, 0.2, 0)[k])


def pluck(note, t, g=0.10, dec=6.0, pan=0.0):
    n = int(0.8 * SR)
    tt = np.arange(n) / SR
    f = midi(note)
    s = sum(np.sin(2 * np.pi * f * h * tt) / h ** 1.6 * np.exp(-tt * dec * h ** 0.5) for h in range(1, 7))
    place(s * np.minimum(1, tt / 0.003), t, g, pan)


def bass(note, t, dur, g=0.22):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = midi(note)
    s = np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt) + 0.12 * np.sin(6 * np.pi * f * tt)
    place(s * env(n, a=0.008, d=dur * 0.6, s=0.5, rel=0.05), t, g)


def tick(t, freq=2600, g=0.07, pan=0.0):
    n = int(0.05 * SR)
    tt = np.arange(n) / SR
    place(np.sin(2 * np.pi * freq * tt) * np.exp(-tt * 90), t, g, pan)


def chime(note, t, g=0.16, dec=1.6):
    n = int(3.0 * SR)
    tt = np.arange(n) / SR
    f = midi(note)
    s = sum(a * np.sin(2 * np.pi * f * m * tt) * np.exp(-tt * dec * m ** 0.4) for m, a in ((1, 1), (2.0, .4), (2.76, .35), (5.4, .12)))
    place(s, t, g, 0.1)
    place(s, t + 0.011, g * 0.7, -0.3)


def whoosh(t, dur=0.9, g=0.20, rising=True):
    n = int(dur * SR)
    x = np.linspace(0, 1, n)
    shape = np.sin(np.pi * (x if rising else 1 - x) ** (1.6 if rising else 0.6)) ** 2
    noise = rng.standard_normal(n)
    bright = np.diff(noise, prepend=0)
    mix = (1 - x) * noise * 0.5 + x * bright if rising else x * noise * 0.5 + (1 - x) * bright
    # Soften: average adjacent samples (a gentle low-pass) and keep transitions under the music.
    soft = np.convolve(mix, np.ones(6) / 6, mode="same")
    place(soft * shape, t - (dur * 0.8 if rising else 0), g * 0.45, pan=-0.3)
    place(soft[::-1] * shape, t - (dur * 0.8 if rising else 0), g * 0.3, pan=0.3)


def riser(t0, t1, g=0.15):
    n = int((t1 - t0) * SR)
    x = np.linspace(0, 1, n)
    noise = np.diff(rng.standard_normal(n), prepend=0)
    tone = np.sin(2 * np.pi * np.cumsum(200 + 1400 * x ** 2) / SR)
    noise = np.convolve(noise, np.ones(4) / 4, mode="same")
    place((noise * 0.5 + tone * 0.18) * x ** 2.2, t0, g)


def impact(t, g=0.8):
    kick(t, g)
    n = int(2.5 * SR)
    tt = np.arange(n) / SR
    place(np.sin(2 * np.pi * 38 * tt) * np.exp(-tt * 1.6), t, 0.35)
    noise = rng.standard_normal(n)
    place(noise * np.exp(-tt * 9), t, 0.10)


# Chords (MIDI): A minor progression, lifting to the relative major at the drop.
Am, F, C, G = [57, 60, 64, 71], [53, 57, 60, 67], [48, 55, 60, 64], [55, 59, 62, 69]
bar = 4 * BEAT

# Cut (seconds): intro 0-3.4 | incident 3.4-7.2 | real UI 7.2-13.0 | investigation 13.0-17.6 | patch 17.6-21.6
# | real UI build 21.6-27.1 | DROP 27.1 verification | real UI 31.9-36.9 | stats 36.9-40.4 | outro 40.4-45


def groove(t0, t1, chords, kick_pattern=(0, 2), clap_on=(1, 3), clap_from=0.0, arp_gain=0.075, pad_gain=0.02, bass_off=-24):
    t, k = t0, 0
    while t < t1 - 0.01:
        chord = chords[(k // 4) % len(chords)]
        b = k % 4
        if b in kick_pattern:
            kick(t, 0.64)
        if b in clap_on and t >= clap_from:
            clap(t, 0.21)
        hat(t + BEAT / 2, 0.09)
        hat(t, 0.045, 80, -0.25)
        for j in range(2):
            pluck(chord[(k * 2 + j) % 4] + 12, t + j * BEAT / 2, arp_gain, 7, pan=(-0.35, 0.35)[j])
        if b == 0:
            bass(chord[0] + bass_off, t, bar * 0.95, 0.20)
            pad_chord(chord, t, bar, pad_gain, bright=3)
        t += BEAT
        k += 1


# Intro: pad, riser, title impact.
pad_chord([45, 57, 64, 71], 0.0, 3.7, 0.045, bright=4)
riser(0.0, 0.8, 0.07)
impact(0.8, 0.55)
chime(81, 0.85, 0.07)
chime(88, 1.15, 0.05)
whoosh(3.4, 0.8, 0.16)

# Incident: tense pulse, dissonant hit when the 500 shakes.
for k in range(int(3.8 / (BEAT / 2))):
    bass(33, 3.4 + k * BEAT / 2, BEAT / 2 * 0.9, 0.16 + 0.04 * (k % 2 == 0))
pad_chord([45, 52, 58], 3.4, 3.8, 0.035, bright=3)
for t in (4.3, 4.42):
    pluck(70, t, 0.10, 3)
    pluck(69, t + 0.06, 0.08, 3)
kick(4.3, 0.6)
for k in range(3):
    tick(5.4 + k * 0.5, 1800, 0.05, pan=0.5)
whoosh(7.2, 0.8, 0.16)

# Real UI + investigation + patch: the groove.
groove(7.2, 21.6, [Am, F, C, G], clap_from=9.0)
for i in range(6):
    tick(13.0 + 0.8 + i * 0.5, 3200, 0.06, pan=-0.4 + 0.15 * i)
chime(84, 13.0 + 3.3, 0.08)
for i in range(34):
    tick(18.9 + i * 0.045 + rng.uniform(0, 0.012), 4200 + rng.uniform(-400, 400), 0.022, pan=rng.uniform(-0.3, 0.3))
whoosh(13.0, 0.7, 0.13)
whoosh(17.6, 0.7, 0.13)
whoosh(21.6, 0.8, 0.15)

# Real UI build-up into the drop.
t, k = 21.6, 0
while t < 26.6:
    if k % 2 == 0:
        kick(t, 0.6)
    hat(t + BEAT / 2, 0.10)
    if k % 4 == 0:
        bass(33, t, bar * 0.9, 0.2)
        pad_chord([57, 60, 64, 69], t, bar, 0.022, bright=4)
    t += BEAT
    k += 1
chime(76, 22.6, 0.08)   # tests passed (on screen in the clip)
chime(79, 24.0, 0.08)   # image built
chime(83, 25.4, 0.08)   # deployed
roll_t, step = 25.2, 0.18
while roll_t < 27.05:
    clap(roll_t, 0.10 + 0.12 * (roll_t - 25.2) / 1.85)
    roll_t += step
    step = max(0.045, step * 0.86)
riser(24.8, 27.1, 0.20)

# DROP at 27.1: verification, resolved chime, real UI, stats.
impact(27.1, 0.75)
groove(27.1, 40.3, [[48, 55, 60, 64], [55, 59, 62, 67], [57, 60, 64, 69], [53, 57, 60, 65]], arp_gain=0.07, pad_gain=0.026, bass_off=-12)
for i in range(15):
    tick(27.7 + i * 0.17, 1800 + i * 90, 0.06, pan=-0.5 + i / 15)
chime(79, 30.5, 0.16)
chime(84, 30.65, 0.12)
chime(91, 30.85, 0.08)
whoosh(31.9, 0.8, 0.13)
whoosh(36.9, 0.8, 0.13)

# Outro.
impact(40.4, 0.6)
pad_chord([48, 55, 64, 67, 72], 40.4, 4.6, 0.045, bright=5)
chime(84, 41.8, 0.12, 1.0)
chime(91, 41.95, 0.07, 1.0)

# Reverb: exponentially decaying stereo noise impulse response, mixed at 22 %.
ir_len = int(2.4 * SR)
decay = np.exp(-np.arange(ir_len) / SR * 3.0)
for ch_index, ch in enumerate((L, R)):
    ir = rng.standard_normal(ir_len) * decay
    ir /= np.sqrt(np.sum(ir ** 2))
    size = 1 << int(np.ceil(np.log2(N + ir_len)))
    wet = np.fft.irfft(np.fft.rfft(ch, size) * np.fft.rfft(ir, size), size)[:N]
    mixed = ch * 0.84 + wet * 0.22
    if ch_index == 0:
        L = mixed
    else:
        R = mixed

fade = np.ones(N)
fade_n = int(1.6 * SR)
fade[-fade_n:] = np.linspace(1, 0, fade_n) ** 1.5
stereo = np.stack([L, R], axis=1) * fade[:, None]
stereo = np.tanh(stereo * 1.25) / np.tanh(1.25)
stereo *= 0.89 / np.max(np.abs(stereo))
pcm = (stereo * 32767).astype(np.int16)
with wave.open(sys.argv[1] if len(sys.argv) > 1 else "music.wav", "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("wrote", len(pcm) / SR, "s")
