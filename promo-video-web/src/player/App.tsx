import { useCallback, useEffect, useRef, useState } from 'react';
import { Engine } from '../core/engine';
import { AudioEngine } from '../core/audio';
import { FPS, OPENING_AUDIO, OPENING_DURATION, STILLS } from '../core/timeline';

const DURATION = OPENING_DURATION;
const fmt = (t: number) => `${t.toFixed(2)}s · 第 ${Math.round(t * FPS)} 帧`;

export function App() {
  const hostRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<Engine | null>(null);
  const audioRef = useRef<AudioEngine | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(() => {
    const q = Number(new URLSearchParams(location.search).get('t'));
    return Number.isFinite(q) ? Math.min(DURATION, Math.max(0, q)) : 0;
  });
  const [playing, setPlaying] = useState(false);
  const [subtitles, setSubtitles] = useState(true);
  const [sound, setSound] = useState(true);
  const [still, setStill] = useState<string | null>(null);
  const timeRef = useRef(time);
  timeRef.current = time;

  // 初始化
  useEffect(() => {
    const engine = new Engine();
    engineRef.current = engine;
    hostRef.current!.appendChild(engine.frameCanvas);
    const audio = new AudioEngine(OPENING_AUDIO);
    audioRef.current = audio;
    Promise.all([engine.init(), audio.preload()])
      .then(() => setReady(true))
      .catch((e: unknown) => setError(String(e instanceof Error ? e.message : e)));
    return () => {
      audio.stop();
      engine.frameCanvas.remove();
    };
  }, []);

  // 渲染：任何时间 / 开关变化都重新渲染对应帧
  useEffect(() => {
    const e = engineRef.current;
    if (!ready || !e) return;
    if (still) e.renderStill(e.stillById(still), { subtitles });
    else e.renderAt(time, { subtitles });
  }, [ready, time, subtitles, still]);

  // 播放循环：按真实时间推进，渲染慢时自动跳帧，时间轴始终与声音同步
  useEffect(() => {
    if (!playing) return;
    const audio = audioRef.current!;
    audio.enabled = sound;
    const startT = timeRef.current >= DURATION ? 0 : timeRef.current;
    audio.start(startT);
    const t0 = performance.now();
    let raf = 0;
    const tick = () => {
      const t = startT + (performance.now() - t0) / 1000;
      if (t >= DURATION) {
        setTime(DURATION);
        setPlaying(false);
        return;
      }
      setTime(Math.floor(t * FPS) / FPS);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      audio.stop();
    };
  }, [playing, sound]);

  const seek = useCallback((t: number) => {
    setStill(null);
    setPlaying(false);
    setTime(Math.min(DURATION, Math.max(0, Math.round(t * FPS) / FPS)));
  }, []);

  const screenshot = useCallback(() => {
    const e = engineRef.current;
    if (!e) return;
    e.frameCanvas.toBlob((b) => {
      if (!b) return;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(b);
      a.download = still ? `${still}.png` : `frame_${time.toFixed(3)}s.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    }, 'image/png');
  }, [time, still]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.target instanceof HTMLInputElement && ev.target.type !== 'range') return;
      if (ev.code === 'Space') {
        ev.preventDefault();
        setStill(null);
        setPlaying((p) => !p);
      } else if (ev.code === 'ArrowRight') seek(timeRef.current + 1 / FPS);
      else if (ev.code === 'ArrowLeft') seek(timeRef.current - 1 / FPS);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [seek]);

  return (
    <div className="player">
      <div className="viewport">
        <div className="frame" ref={hostRef} />
        {!ready && !error && <div className="loading">加载原始模型与屏幕素材…</div>}
        {error && <div className="loading error">加载失败：{error}</div>}
      </div>

      {/* 编辑器控件：位于成片画布之外，不会进入任何导出帧 */}
      <div className="controls">
        <button
          onClick={() => {
            setStill(null);
            setPlaying((p) => !p);
          }}
          disabled={!ready}
        >
          {playing ? '暂停' : '播放'}
        </button>
        <button onClick={() => seek(time - 1 / FPS)} disabled={!ready}>
          ◀ 1帧
        </button>
        <button onClick={() => seek(time + 1 / FPS)} disabled={!ready}>
          1帧 ▶
        </button>
        <input
          className="scrub"
          type="range"
          min={0}
          max={DURATION}
          step={1 / FPS}
          value={time}
          onChange={(e) => seek(Number(e.target.value))}
          disabled={!ready}
        />
        <span className="tc">{still ? '静帧' : fmt(time)}</span>
        <label>
          <input type="checkbox" checked={subtitles} onChange={(e) => setSubtitles(e.target.checked)} /> 字幕
        </label>
        <label title={audioRef.current?.hasCues ? '' : '开场阶段按要求无配音 / 音乐'}>
          <input type="checkbox" checked={sound} onChange={(e) => setSound(e.target.checked)} /> 声音
        </label>
        <button onClick={screenshot} disabled={!ready}>
          截图当前帧
        </button>
      </div>
      <div className="controls secondary">
        <span className="muted">关键画面：</span>
        {STILLS.map((s) => (
          <button
            key={s.id}
            className={still === s.id ? 'active' : ''}
            onClick={() => {
              setPlaying(false);
              setStill(s.id);
            }}
            disabled={!ready}
          >
            {s.label}
          </button>
        ))}
        <span className="muted">空格 播放/暂停 · ←/→ 逐帧 · 地址栏 ?t=6.6 直达指定时间</span>
      </div>
    </div>
  );
}
