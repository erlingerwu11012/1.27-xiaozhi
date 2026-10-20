import { createRoot } from 'react-dom/client';
import { App } from './player/App';
import { Engine } from './core/engine';
import { FPS, OPENING_DURATION, STILLS } from './core/timeline';
import './player/player.css';

const params = new URLSearchParams(location.search);

declare global {
  interface Window {
    __promo?: {
      ready: boolean;
      error?: string;
      info?: Record<string, unknown>;
      fps: number;
      duration: number;
      stills: { id: string; label: string }[];
      renderFrame: (t: number, subtitles?: boolean) => string;
      renderStill: (id: string, subtitles?: boolean) => string;
    };
  }
}

if (params.get('mode') === 'export') {
  // 无头导出模式：页面上只有成片画布，没有任何编辑器控件
  document.body.className = 'export';
  const engine = new Engine();
  document.getElementById('root')!.appendChild(engine.frameCanvas);
  const api: NonNullable<Window['__promo']> = {
    ready: false,
    fps: FPS,
    duration: OPENING_DURATION,
    stills: STILLS.map(({ id, label }) => ({ id, label })),
    renderFrame: (t, subtitles = true) => {
      engine.renderAt(t, { subtitles });
      return engine.frameCanvas.toDataURL('image/png');
    },
    renderStill: (id, subtitles = true) => {
      engine.renderStill(engine.stillById(id), { subtitles });
      return engine.frameCanvas.toDataURL('image/png');
    },
  };
  window.__promo = api;
  // 调试入口：仅导出模式可用，便于自查（隐藏零件、指定机位等）
  (window as unknown as { __engine: Engine }).__engine = engine;
  engine
    .init()
    .then(() => {
      api.info = engine.info;
      api.ready = true;
    })
    .catch((e: unknown) => {
      api.error = String(e instanceof Error ? e.stack : e);
    });
} else {
  createRoot(document.getElementById('root')!).render(<App />);
}
