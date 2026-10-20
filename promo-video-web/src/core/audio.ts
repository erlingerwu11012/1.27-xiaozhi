/**
 * 声音轨：与画面共用时间轴。开场阶段没有任何音轨（按要求不配音、不加音乐）；
 * 完整版只需在 timeline.ts 的 AudioCue 列表登记文件即可替换 / 增删。
 */
import type { AudioCue } from './timeline';

export class AudioEngine {
  private ctx: AudioContext | null = null;
  private buffers = new Map<string, AudioBuffer>();
  private playing: AudioBufferSourceNode[] = [];
  private master: GainNode | null = null;
  enabled = true;

  constructor(private cues: AudioCue[], private base = './') {}

  async preload() {
    if (!this.cues.length) return;
    this.ctx = new AudioContext();
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    await Promise.all(
      this.cues.map(async (c) => {
        const buf = await (await fetch(this.base + c.src)).arrayBuffer();
        this.buffers.set(c.id, await this.ctx!.decodeAudioData(buf));
      }),
    );
  }

  /** 从时间 t 开始播放所有音轨（拖动 / 暂停后重新调用） */
  start(t: number) {
    this.stop();
    if (!this.ctx || !this.master || !this.enabled) return;
    void this.ctx.resume();
    const now = this.ctx.currentTime + 0.03;
    for (const c of this.cues) {
      const buf = this.buffers.get(c.id);
      if (!buf || c.start + buf.duration <= t) continue;
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      const g = this.ctx.createGain();
      g.gain.value = c.gain;
      src.connect(g).connect(this.master);
      const offset = Math.max(0, t - c.start);
      src.start(now + Math.max(0, c.start - t), offset);
      this.playing.push(src);
    }
  }

  stop() {
    for (const s of this.playing) {
      try {
        s.stop();
      } catch {
        /* 已停止 */
      }
    }
    this.playing = [];
  }

  get hasCues() {
    return this.cues.length > 0;
  }
}
