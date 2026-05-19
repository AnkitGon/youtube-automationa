"""
Cinematic SFX layer for promo_silent.mp4 -> promo_video.mp4
Timing matches storyboard:
  0-5s   intro
  5-10s  promise
  10-18s telegram
  18-26s youtube
  26-34s terminal
  34-40s CTA
All SFX procedural (numpy).
"""
import numpy as np
from moviepy import VideoFileClip, AudioArrayClip
from pathlib import Path

SR = 44100
HERE = Path(__file__).parent
SRC  = HERE / "promo_silent.mp4"
OUT  = HERE / "promo_video.mp4"

# ── Primitives ───────────────────────────────────────────────────────────
def silence(d): return np.zeros((int(SR*d), 2))
def stereo(m):  return np.column_stack([m, m])

def sine(freq, dur, amp=0.4, fi=0.005, fo=0.05):
    n = int(SR*dur); t = np.linspace(0, dur, n, endpoint=False)
    w = amp*np.sin(2*np.pi*freq*t)
    if fi: w[:int(SR*fi)] *= np.linspace(0,1,int(SR*fi))
    if fo: w[-int(SR*fo):] *= np.linspace(1,0,int(SR*fo))
    return stereo(w)

def whoosh(dur=0.8, amp=0.35):
    n=int(SR*dur); t=np.linspace(0,1,n)
    noise=np.random.randn(n)
    env=np.sin(np.pi*t)**1.4
    k=20; noise=np.convolve(noise, np.ones(k)/k, mode="same")
    return stereo(np.clip(amp*noise*env, -1, 1))

def boom(dur=0.7, amp=0.55, freq=42):
    n=int(SR*dur); t=np.linspace(0,dur,n)
    env=np.exp(-t*5)
    fi=freq*(1+4*np.exp(-t*25))
    ph=2*np.pi*np.cumsum(fi)/SR
    w=amp*np.sin(ph)*env + amp*0.35*np.sin(2*np.pi*110*t)*np.exp(-t*8)
    return stereo(np.clip(w,-1,1))

def riser(dur=1.5, amp=0.32):
    n=int(SR*dur); t=np.linspace(0,1,n)
    freq=80+(700-80)*(t**2)
    ph=2*np.pi*np.cumsum(freq)/SR
    w=amp*np.sin(ph)*(t**0.5) + amp*0.4*np.sin(2*ph)*(t**0.5)
    fo=int(SR*0.2); w[-fo:]*=np.linspace(1,0,fo)
    return stereo(np.clip(w,-1,1))

def tick(amp=0.22, f=2200):
    n=int(SR*0.020); t=np.linspace(0,0.020,n)
    return stereo(amp*np.sin(2*np.pi*f*t)*np.exp(-t*250))

def shimmer(dur=0.7, amp=0.18):
    n=int(SR*dur); t=np.linspace(0,dur,n)
    env=np.exp(-t*3.5); w=np.zeros(n)
    for f in [2093,2637,3136,4186]:
        w += np.sin(2*np.pi*f*t)*env/4
    return stereo(amp*w)

def pop(freq=900, amp=0.25):
    n=int(SR*0.10); t=np.linspace(0,0.10,n)
    w=amp*np.sin(2*np.pi*freq*t)*np.exp(-t*35)
    w+=amp*0.3*np.sin(2*np.pi*freq*1.5*t)*np.exp(-t*50)
    return stereo(w)

def beep(freq, dur=0.18, amp=0.22):
    n=int(SR*dur); t=np.linspace(0,dur,n)
    return stereo(amp*np.sin(2*np.pi*freq*t)*np.exp(-t*6))

def typing(n_keys=8, amp=0.14):
    parts=[]
    for _ in range(n_keys):
        f=np.random.uniform(1400,2100)
        nf=int(SR*0.012); t=np.linspace(0,0.012,nf)
        w=amp*np.sin(2*np.pi*f*t)*np.exp(-t*350)
        w+=amp*0.3*np.random.randn(nf)*np.exp(-t*800)
        parts.append(stereo(w))
        parts.append(silence(np.random.uniform(0.05,0.10)))
    return np.vstack(parts)

def arpeggio(amp=0.26):
    notes=[(523,0.18),(659,0.18),(784,0.22),(1047,0.50)]
    parts=[]
    for f,dur in notes:
        n=int(SR*dur); t=np.linspace(0,dur,n)
        env=np.exp(-t*4)
        w=amp*(np.sin(2*np.pi*f*t)+0.3*np.sin(2*np.pi*f*2*t))*env
        parts.append(stereo(w)); parts.append(silence(0.04))
    return np.vstack(parts)

def msg_blip(amp=0.30):
    n=int(SR*0.18); t=np.linspace(0,0.18,n)
    f=880+220*np.exp(-t*30); ph=2*np.pi*np.cumsum(f)/SR
    return stereo(amp*np.sin(ph)*np.exp(-t*9))

def drone(dur, amp=0.05, base=50):
    n=int(SR*dur); t=np.linspace(0,dur,n); w=np.zeros(n)
    for h,g in [(1,1),(2,0.5),(3,0.25),(5,0.1)]:
        w += g*np.sin(2*np.pi*base*h*t + h*0.3)
    lfo=0.6+0.4*np.sin(2*np.pi*0.18*t); w*=lfo
    fi=int(SR*0.6); fo=int(SR*0.6)
    w[:fi]*=np.linspace(0,1,fi); w[-fo:]*=np.linspace(1,0,fo)
    return stereo(amp*w)

def counter_tick(amp=0.06):
    n=int(SR*0.025); t=np.linspace(0,0.025,n)
    return stereo(amp*np.sin(2*np.pi*2600*t)*np.exp(-t*200))

# ── Master track ─────────────────────────────────────────────────────────
TOTAL = 40.0
track = np.zeros((int(SR*TOTAL), 2))

def place(s, t, g=1.0):
    a=int(t*SR); b=a+len(s)
    if b>len(track): s=s[:len(track)-a]; b=len(track)
    if a<len(track): track[a:b] += s*g

# ── 0-5 INTRO ────────────────────────────────────────────────────────────
place(drone(5.0, amp=0.05, base=55), 0)
place(riser(1.2, amp=0.28),         0.0)   # ring draws
place(boom(0.9, amp=0.5, freq=42),  1.0)   # ring resolves
place(whoosh(0.7, amp=0.22),        1.0)
place(shimmer(0.8, amp=0.15),       1.2)
place(whoosh(0.5, amp=0.16),        2.3)   # title settles
place(beep(660, 0.22, amp=0.10),    3.0)   # subtitle
place(beep(880, 0.18, amp=0.10),    3.5)   # divider line

# ── 5-10 PROMISE ─────────────────────────────────────────────────────────
place(drone(5.0, amp=0.05, base=60), 5.0)
place(whoosh(0.5, amp=0.18),        5.2)   # line 1
place(whoosh(0.7, amp=0.26),        6.2)   # line 2 (BIG)
place(boom(0.6, amp=0.32, freq=50), 6.3)
place(whoosh(0.5, amp=0.16),        7.5)   # line 3
place(beep(1100, 0.20, amp=0.12),   7.7)
place(pop(1400, amp=0.18),          8.7)   # red dot

# ── 10-18 TELEGRAM ───────────────────────────────────────────────────────
place(drone(8.0, amp=0.05, base=58), 10.0)
place(whoosh(0.5, amp=0.18),        10.0)   # scene transition
place(whoosh(0.7, amp=0.22),        11.0)   # phone slides in
place(boom(0.5, amp=0.20, freq=55), 11.1)

# Messages: m1 lt=0.18 -> 11.44; m2 lt=0.32 -> 12.56; m3 lt=0.52 -> 14.16; m4 lt=0.72 -> 15.76
place(msg_blip(amp=0.30),           11.44)  # user msg 1
place(msg_blip(amp=0.30),           12.56)  # bot reply 1
place(msg_blip(amp=0.30),           14.16)  # user /forza
# typing burst before m4
place(typing(n_keys=6, amp=0.10),   14.7)
place(msg_blip(amp=0.32),           15.76)  # bot final

# annotation slide in: lt=0.35 -> 12.8
place(whoosh(0.4, amp=0.10),        12.8)

# ── 18-26 YOUTUBE ────────────────────────────────────────────────────────
place(drone(8.0, amp=0.05, base=55), 18.0)
place(whoosh(0.7, amp=0.28),        18.0)   # cut transition
place(boom(0.7, amp=0.40, freq=55), 18.1)
place(whoosh(0.5, amp=0.18),        18.9)   # card appears
place(shimmer(0.6, amp=0.12),       19.3)

# Counter ticks during animation 18.5-22 (eased rapid → slowing)
for i in range(40):
    # acceleration curve: tick rate slows
    progress = i / 40
    t_pos = 19.0 + 3.5 * (progress ** 0.7)
    place(counter_tick(amp=0.04),    t_pos)

# Badge reveal at lt=0.25 -> 20.0
place(pop(1200, amp=0.16),          20.0)

# ── 26-34 TERMINAL ───────────────────────────────────────────────────────
place(drone(8.0, amp=0.05, base=60), 26.0)
place(whoosh(0.7, amp=0.25),        26.0)   # cut
place(boom(0.5, amp=0.25, freq=60), 26.2)
place(whoosh(0.5, amp=0.16),        26.8)   # terminal in

# Line 1 typing: lt=0.15-0.30 -> 27.2-28.4
place(typing(n_keys=4, amp=0.13),   27.25)
place(beep(700, 0.20, amp=0.18),    28.3)   # check

# Line 2 typing: lt=0.36-0.55 -> 28.88-30.4
place(typing(n_keys=12, amp=0.13),  28.95)
place(beep(800, 0.20, amp=0.18),    30.4)   # check

# Line 3 typing: lt=0.62-0.75 -> 30.96-32.0
place(typing(n_keys=4, amp=0.13),   31.0)
place(beep(900, 0.20, amp=0.18),    32.0)   # check

# Success chord at end
place(arpeggio(amp=0.18),           32.5)

# ── 34-40 CTA ────────────────────────────────────────────────────────────
place(drone(6.0, amp=0.07, base=55), 34.0)
place(riser(1.5, amp=0.32),         33.5)   # build into "Start today"
place(boom(0.9, amp=0.55, freq=45), 34.5)   # "Start today" hits
place(whoosh(0.7, amp=0.28),        34.5)
place(boom(0.9, amp=0.52, freq=55), 35.7)   # "Post forever"
place(shimmer(1.0, amp=0.18),       36.0)
place(whoosh(0.4, amp=0.12),        37.0)   # divider
place(beep(880, 0.4, amp=0.14),     37.5)   # URL
place(arpeggio(amp=0.20),           38.0)   # final flourish

# ── Master bus ───────────────────────────────────────────────────────────
peak = np.max(np.abs(track))
if peak > 0:
    track = track / peak * 0.85
track = np.tanh(track * 1.3) / 1.3
# Haas stereo width
d = int(SR * 0.008)
track[d:, 1] = track[d:, 1] * 0.95 + track[:-d, 1] * 0.25

# ── Compose ──────────────────────────────────────────────────────────────
print("Loading silent video...")
v = VideoFileClip(str(SRC))
print(f"  Duration: {v.duration:.2f}s")
print("Building audio clip...")
a = AudioArrayClip(track, fps=SR).with_duration(v.duration)
print("Compositing & encoding...")
v.with_audio(a).write_videofile(
    str(OUT),
    codec="libx264",
    audio_codec="aac",
    audio_fps=SR,
    preset="medium",
    ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p", "-b:a", "192k",
                    "-movflags", "+faststart"],
    logger=None,
)
print(f"-> {OUT}")
