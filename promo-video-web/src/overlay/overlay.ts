/**
 * 成片内的图形层（字幕 / 对话框），用 Canvas2D 直接画进 1920×1080 成片帧，
 * 因此浏览器内截图、无头导出与预览完全一致；编辑器控件不在这张画布上。
 */
import type { DialogueLine } from '../core/timeline';
import { HEIGHT, WIDTH } from '../core/timeline';
import { clamp01, smoothstep } from '../core/math';

export const FONT_STACK = `"Noto Sans SC","Noto Sans CJK SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif`;

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

/**
 * 对话框：右侧竖排，左对齐；“你”（画外音）与“它”（设备）区分标签，
 * 不覆盖产品（产品在左三分区域）。
 */
export function drawDialogue(
  ctx: CanvasRenderingContext2D,
  scene: CanvasImageSource,
  lines: DialogueLine[],
  t: number,
) {
  const x0 = 1080;
  let y = 392;
  const maxW = 660;
  for (const line of lines) {
    const a = smoothstep(line.in, line.in + 0.45, t);
    if (a <= 0) continue;
    const rise = (1 - a) * 14;
    const isUser = line.speaker === 'user';
    const label = isUser ? '你' : '它';
    const sub = isUser ? '画外音' : '桌面伙伴';

    ctx.save();
    ctx.globalAlpha = a;
    ctx.font = `400 40px ${FONT_STACK}`;
    const textW = Math.min(maxW, ctx.measureText(line.text).width);
    const padX = 34,
      padTop = 72,
      padBottom = 34;
    const w = textW + padX * 2;
    const h = padTop + 44 + padBottom;
    const bx = x0,
      by = y + rise;

    // 磨砂玻璃：取场景对应区域模糊后作为底
    ctx.save();
    roundRect(ctx, bx, by, w, h, 22);
    ctx.clip();
    ctx.filter = 'blur(26px) brightness(0.55) saturate(0.9)';
    ctx.drawImage(scene, 0, 0, WIDTH, HEIGHT);
    ctx.filter = 'none';
    ctx.fillStyle = isUser ? 'rgba(18,18,20,0.38)' : 'rgba(26,22,18,0.34)';
    ctx.fillRect(bx, by, w, h);
    ctx.restore();

    roundRect(ctx, bx + 0.5, by + 0.5, w - 1, h - 1, 22);
    ctx.strokeStyle = isUser ? 'rgba(255,255,255,0.13)' : 'rgba(255,214,170,0.26)';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // 标签行
    ctx.fillStyle = isUser ? 'rgba(235,235,240,0.92)' : 'rgba(255,214,170,0.95)';
    ctx.beginPath();
    ctx.arc(bx + padX + 6, by + 38, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = `500 22px ${FONT_STACK}`;
    ctx.fillText(label, bx + padX + 22, by + 46);
    ctx.fillStyle = 'rgba(255,255,255,0.42)';
    ctx.font = `400 20px ${FONT_STACK}`;
    ctx.fillText(sub, bx + padX + 22 + ctx.measureText(label).width + 30, by + 45);

    // 正文
    ctx.fillStyle = 'rgba(248,246,242,0.96)';
    ctx.font = `400 40px ${FONT_STACK}`;
    ctx.fillText(line.text, bx + padX, by + padTop + 36);
    ctx.restore();
    y += h + 26;
  }
}

/** 可选的极简标签（如“此前”“几天后”），完整版使用 */
export function drawTag(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, a: number) {
  ctx.save();
  ctx.globalAlpha = clamp01(a);
  ctx.font = `500 24px ${FONT_STACK}`;
  ctx.fillStyle = 'rgba(255,255,255,0.7)';
  ctx.fillText(text, x, y);
  ctx.restore();
}
