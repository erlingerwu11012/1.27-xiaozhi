"""Print a loudness envelope (dBFS per window) so structure can be checked without listening."""
import sys, numpy as np, soundfile as sf
for p in sys.argv[2:]:
    x, sr = sf.read(p); x = x.mean(1) if x.ndim > 1 else x
    w = int(float(sys.argv[1]) * sr)
    db = [20 * np.log10(np.sqrt((x[i:i + w] ** 2).mean()) + 1e-9) for i in range(0, len(x) - w + 1, w)]
    lead = np.argmax(np.abs(x) > 0.01) / sr
    print(f"{p.split('/')[-1]:22s} dur={len(x)/sr:6.2f}s lead_silence={lead:4.2f}s peak={20*np.log10(np.abs(x).max()+1e-9):5.1f}dB")
    print("   " + " ".join(f"{d:4.0f}" for d in db))
