/**
 * 官方语音（/official-tts/*）的演示数据：我的音色（设计 / 复刻）、配音任务、管理员价格版本与账单核对记录。
 * 价格金额只是演示值（版本名带“演示”），不代表真实售价；复刻音频只保存文件名与大小，不保存音频内容。
 */
import { seed } from '../core';
import { DEMO_USERS } from './core';

const MIN = 60000;
const iso = (ms) => new Date(ms).toISOString();

export function buildOfficialTtsSeed(now = Date.now()) {
  const u = DEMO_USERS.user.id;
  const adm = DEMO_USERS.admin.id;
  const voices = [
    { id: 501, userId: u, kind: 'design', name: '温柔旁白（演示）', prompt: '温柔女声，语速适中，适合有声书旁白', previewText: '欢迎使用文本朗读，这是一段设计的音色。', status: 'available', upstreamVoiceId: 'demo-design-voice-0501', hasPreview: true, errorMsg: '', createdAt: iso(now - 9 * 1440 * MIN), tone: 392 },
    { id: 502, userId: u, kind: 'design', name: '沉稳播报（演示）', prompt: '沉稳男声，吐字清晰，适合资讯播报', previewText: '欢迎使用文本朗读，这是一段设计的音色。', status: 'available', upstreamVoiceId: 'demo-design-voice-0502', hasPreview: false, errorMsg: '', createdAt: iso(now - 4 * 1440 * MIN), tone: 262 },
    { id: 503, userId: u, kind: 'clone', name: '我的声音（演示）', status: 'available', upstreamVoiceId: 'demo-clone-voice-0503', hasPreview: true, errorMsg: '', createdAt: iso(now - 6 * 1440 * MIN), file: { name: '我的声音.wav', size: 412000, type: 'audio/wav' }, tone: 330 },
    { id: 504, userId: u, kind: 'clone', name: '客厅录音（演示）', status: 'failed', upstreamVoiceId: null, hasPreview: false, errorMsg: '演示：录音里有多人说话，无法复刻。请上传单人清晰录音后重试。', createdAt: iso(now - 2 * 1440 * MIN), file: { name: '客厅录音.wav', size: 286000, type: 'audio/wav' }, tone: 294 },
    { id: 509, userId: adm, kind: 'design', name: '联调测试音色（演示）', prompt: '中性声音，用于联调', previewText: '欢迎使用文本朗读，这是一段设计的音色。', status: 'available', upstreamVoiceId: 'demo-design-voice-0509', hasPreview: true, errorMsg: '', createdAt: iso(now - 20 * 1440 * MIN), tone: 440 },
  ];
  const req = (o) => JSON.stringify({ jobType: 'dubbing', format: 'wav', volume: 50, rate: 1, languageHints: ['zh'], ...o });
  const jobs = [
    { id: 701, userId: u, jobType: 'dubbing', status: 'done', voiceCode: 'longanlingxi', synthesisText: '夜色渐深，窗外的风轻轻拂过树梢。她合上书本，轻声说道：明天会更好。（演示）', requestJson: req({ voice: 'longanlingxi', text: '夜色渐深，窗外的风轻轻拂过树梢。她合上书本，轻声说道：明天会更好。（演示）' }), createdAt: iso(now - 3 * 1440 * MIN), finishedAt: iso(now - 3 * 1440 * MIN + MIN), charged: 1.2, held: 0, state: 'settled' },
    { id: 702, userId: u, jobType: 'dubbing', status: 'done', voiceCode: 'demo-clone-voice-0503', synthesisText: '[laughing]今天的会开得很顺利，晚上一起吃饭吧。（演示）', requestJson: req({ voice: 'demo-clone-voice-0503', text: '[laughing]今天的会开得很顺利，晚上一起吃饭吧。（演示）', rate: 1.2, format: 'mp3' }), createdAt: iso(now - 26 * 60 * MIN), finishedAt: iso(now - 26 * 60 * MIN + MIN), charged: 0.8, held: 0, state: 'settled' },
    { id: 703, userId: u, jobType: 'dubbing', status: 'failed', voiceCode: 'longanqian', synthesisText: '演示：这条任务模拟合成失败的情况。', requestJson: req({ voice: 'longanqian', text: '演示：这条任务模拟合成失败的情况。', lang: 'zh', dialect: '四川话' }), errorMsg: '演示：合成失败，冻结的点数已释放。', createdAt: iso(now - 50 * MIN), finishedAt: iso(now - 49 * MIN), charged: 0, held: 0, state: 'released' },
    { id: 709, userId: adm, jobType: 'dubbing', status: 'uncertain', voiceCode: 'longanlingxi', synthesisText: '联调用的配音任务（演示）', requestJson: req({ voice: 'longanlingxi', text: '联调用的配音任务（演示）' }), createdAt: iso(now - 2 * 1440 * MIN), finishedAt: null, charged: 0.3, held: 0.9, state: 'manual_review' },
  ];
  const price = (id, operation, unit, amount, status, lifecycleStatus, version, priceKind = 'sale_points') => ({ id, priceKind, operation, unit, amount, status, lifecycleStatus, version });
  return {
    ttsVoicesMine: voices,
    ttsJobs: jobs,
    ttsAdmin: {
      enhancedFlag: 'on（演示）',
      allowUsers: 'demo_user, demo_admin',
      prices: [
        price(801, 'synthesize', 'weighted_character', 0.0002, 'published', 'active', '演示价格 v1'),
        price(802, 'design', 'official_units', 0.05, 'published', 'active', '演示价格 v1'),
        price(803, 'clone', 'official_units', 0.08, 'published', 'active', '演示价格 v1'),
        price(804, 'synthesize', 'weighted_character', 0.00025, 'draft', 'draft', '演示价格 v2'),
        price(805, 'synthesize', 'weighted_character', 0.0001, 'published', 'active', '演示成本 v1', 'cost'),
      ],
      notes: [],
      settlements: [],
    },
  };
}

seed(() => buildOfficialTtsSeed());
