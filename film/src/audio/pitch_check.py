"""Estimate median F0 of voice clips to tell male/female voices apart (AI can't listen)."""
import sys, glob, numpy as np, soundfile as sf

def median_f0(path):
    x, sr = sf.read(path)
    if x.ndim > 1: x = x.mean(1)
    win, hop = int(0.04*sr), int(0.01*sr)
    f0s = []
    for i in range(0, len(x)-win, hop):
        f = x[i:i+win] * np.hanning(win)
        if np.sqrt((f**2).mean()) < 0.02: continue
        ac = np.correlate(f, f, 'full')[win-1:]
        lo, hi = int(sr/400), int(sr/70)
        lag = lo + np.argmax(ac[lo:hi])
        if ac[lag] > 0.3*ac[0]: f0s.append(sr/lag)
    return np.median(f0s) if f0s else 0, len(x)/sr

for p in sorted(glob.glob(sys.argv[1])):
    f0, dur = median_f0(p)
    print(f"{p.split(chr(92))[-1].split('/')[-1]:30s} F0={f0:6.1f}Hz  dur={dur:5.2f}s  -> {'male' if f0 < 165 else 'female'}")
