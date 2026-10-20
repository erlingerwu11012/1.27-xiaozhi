/**
 * /agent/* 其余部分的演示数据：默认角色模板、会话与聊天记录、声纹。
 * 智能体与设备 id 引用 seed/core.js（demo-a-1 … demo-a-4 属于 demo_user，demo-a-9 属于 demo_admin）。
 *
 * 聊天记录说明：
 * - chatType 1 = 用户说的话，2 = 智能体的回复（与原 ChatHistoryDialog 的判断一致）；
 * - 智能体 chatHistoryConf = 2（上报文字 + 语音）时消息带 audioId，= 1（只上报文字）时没有；
 * - 记忆模式为“无记忆”的智能体（demo-a-3）没有聊天记录，首页的“聊天记录”入口本来就是禁用的。
 */
import { seed, nowStr } from '../core';

const at = (msAgo) => nowStr(new Date(Date.now() - msAgo));
const MIN = 60000;
const DAY = 86400000;

/** 对话脚本：[用户, 智能体, 用户, 智能体, ...]。内容是演示用的日常对话 */
const ZH_SCRIPTS = [
  ['今天杭州天气怎么样？', '杭州今天多云，白天大概 22 度，傍晚可能有小雨，出门可以带把伞。', '那我晚点再去跑步吧。', '可以，等雨停了路面干一点再去，跑起来也舒服些。'],
  ['帮我记一下，明天上午十点开组会。', '好，明天上午十点组会，我记下了。需要提前提醒你吗？', '提前半小时吧。', '行，明天九点半提醒你。'],
  ['我有点累，不想写作业了。', '连着写了一下午，累是正常的。要不先站起来走两分钟，喝口水？', '嗯，休息一下再说。', '好，回来我们先挑最短的那一题开始。'],
  ['你觉得纸质书和电子书哪个好？', '我更喜欢纸质书，翻起来能感觉到读了多少；电子书的好处是带着轻。', '我出门一般带 Kindle。', '通勤看确实方便，回家想慢慢读的时候再拿纸质的。'],
  ['{"speaker":"妈妈","content":"晚饭做什么好？"}', '冰箱里如果有西红柿和鸡蛋，做个西红柿炒蛋再配个青菜，二十分钟就够了。', '{"speaker":"妈妈","content":"那就这么定了。"}', '好呀，记得西红柿先炒出汁再放鸡蛋。'],
  ['放首轻松一点的歌。', '好的，给你放一首轻快的钢琴曲。', '声音小一点。', '已经把音量调低了一些。'],
  ['今天学了二次函数，顶点式有点绕。', '顶点式 y = a(x−h)² + k，顶点就是 (h, k)。你先记住“括号里减 h，顶点横坐标就是 h”。', '那 a 是干什么的？', 'a 决定开口方向和胖瘦：a 大于 0 开口向上，绝对值越大越瘦。'],
  ['晚安。', '晚安，今天辛苦了，好好睡一觉。'],
];
const EN_SCRIPTS = [
  ['How do I say "I am looking forward to it" more casually?', 'You could say "Can\'t wait!" or "I\'m excited for it."', 'Can\'t wait for the weekend!', 'Nice, that sounds natural. Any plans?'],
  ['I goed to the park yesterday.', 'Almost! The past tense of "go" is "went": I went to the park yesterday.', 'I went to the park yesterday.', 'Perfect. What did you do there?'],
];

/** 为一个智能体生成 n 个会话（时间从新到旧），返回 { sessions, nextAudio } */
function buildSessions(agentId, { count, scripts, newestMs, gapMs, macs, withAudio, audioStart }) {
  const sessions = [];
  let audio = audioStart;
  for (let i = 0; i < count; i++) {
    const script = scripts[i % scripts.length];
    const startMs = newestMs + i * gapMs + (i % 3) * 17 * MIN;
    const mac = macs[i % macs.length];
    const sessionId = `demo-s-${agentId.replace('demo-a-', '')}-${String(i + 1).padStart(3, '0')}`;
    const messages = script.map((content, j) => {
      // 第 3 句之后隔 2 分钟，演示对话框里的时间分隔
      const offset = j * 20000 + (j >= 2 ? 2 * MIN : 0);
      const msg = {
        id: `${sessionId}-m${j + 1}`,
        chatType: j % 2 === 0 ? 1 : 2,
        content,
        macAddress: mac,
        createdAt: at(startMs - offset),
        audioId: null,
      };
      if (withAudio) {
        audio += 1;
        msg.audioId = `demo-audio-${audio}`;
      }
      return msg;
    });
    sessions.push({ sessionId, agentId, macAddress: mac, createdAt: messages[0].createdAt, messages });
  }
  return { sessions, nextAudio: audio };
}

/** 初始数据。导出给 handler：浏览器里已有旧版演示数据库时，按需补上这里的集合 */
export function buildAgentExtraSeed() {
  let audio = 1000;
  const chats = {};
  const add = (agentId, opts) => {
    const r = buildSessions(agentId, { ...opts, audioStart: audio });
    audio = r.nextAudio;
    chats[agentId] = r.sessions;
  };
  // 小念：最近一次对话 12 分钟前（与首页“最近对话”一致）；会话数超过一页（20），用于演示滚动加载
  add('demo-a-1', { count: 26, scripts: ZH_SCRIPTS, newestMs: 12 * MIN, gapMs: 0.6 * DAY, macs: ['02:00:5E:10:00:01', '02:00:5E:10:00:02'], withAudio: true });
  // 晚安电台：只上报文字（chatHistoryConf = 1）
  add('demo-a-2', { count: 6, scripts: [ZH_SCRIPTS[2], ZH_SCRIPTS[7], ZH_SCRIPTS[3]], newestMs: (5 * 60 + 20) * MIN, gapMs: DAY, macs: ['02:00:5E:10:00:03'], withAudio: false });
  // 英语练习：设备已解绑，保留历史记录
  add('demo-a-4', { count: 2, scripts: EN_SCRIPTS, newestMs: 3 * DAY + 2 * 3600000, gapMs: DAY, macs: ['02:00:5E:10:00:04'], withAudio: false });
  // 管理员的测试机器人
  add('demo-a-9', { count: 3, scripts: [ZH_SCRIPTS[0], ZH_SCRIPTS[5]], newestMs: DAY + 4 * 3600000, gapMs: DAY, macs: ['02:00:5E:10:00:09'], withAudio: true });

  return {
    agentChats: chats,

    // 默认角色模板（管理员维护，新建智能体时使用）。模型字段与 TemplateQuickConfig 提交的字段一致
    agentTemplates: [
      { id: 'demo-t-1', agentCode: '小智', agentName: '自然朋友（演示）', sort: 1, systemPrompt: '你随和、坦诚，像熟人一样交谈。接住对方说的小事，也分享一个具体看法；不用每次安慰、提问或给建议。' },
      { id: 'demo-t-2', agentCode: '小智', agentName: '温柔倾听（演示）', sort: 2, systemPrompt: '你温和、细腻，愿意听人说话。回应对方已经表达的感受和具体处境，少一点分析，多一点平实接话。' },
      { id: 'demo-t-3', agentCode: '小智', agentName: '学习伙伴（演示）', sort: 3, systemPrompt: '你是务实的学习伙伴。帮对方理清重点和步骤，一次只推进一小步；卡住时先问清楚卡在哪里。' },
      { id: 'demo-t-4', agentCode: '小智', agentName: '英语陪练（演示）', sort: 4, systemPrompt: 'You are a patient English speaking partner. Keep sentences short and correct mistakes gently.' },
      { id: 'demo-t-5', agentCode: '小智', agentName: '睡前故事（演示）', sort: 5, systemPrompt: '你会讲温和的睡前故事，语速放慢，情节简单，不出现惊吓内容；对方说困了就道晚安。' },
      { id: 'demo-t-6', agentCode: '小智', agentName: '厨房助手（演示）', sort: 6, systemPrompt: '你熟悉家常菜做法。回答时先说需要的食材，再按步骤说明，每步一句话。' },
      { id: 'demo-t-7', agentCode: '小智', agentName: '运动打卡（演示）', sort: 7, systemPrompt: '你陪对方做日常运动打卡，记录目标、给出简单的动作提示，不做医疗建议。' },
      { id: 'demo-t-8', agentCode: '小智', agentName: '天气播报（演示）', sort: 8, systemPrompt: '你负责简短播报天气，提醒带伞、增减衣物等与天气直接相关的事。' },
      { id: 'demo-t-9', agentCode: '小智', agentName: '故事接龙（演示）', sort: 9, systemPrompt: '你和对方轮流讲故事，每次只接一两句，留下让对方继续的空间。' },
      { id: 'demo-t-10', agentCode: '小智', agentName: '冷静理性（演示）', sort: 10, systemPrompt: '你沉稳、理性，先给明确看法，再用一个与话题有关的理由说明；区分已知和猜测。' },
      { id: 'demo-t-11', agentCode: '小智', agentName: '俏皮调侃（演示）', sort: 11, systemPrompt: '你调皮、机灵，抓住话题的小反差轻轻打趣，玩笑有分寸，不拿对方的能力开玩笑。' },
      { id: 'demo-t-12', agentCode: '小智', agentName: '做事搭档（演示）', sort: 12, systemPrompt: '你务实可靠，对方求助时先找出关键约束，给少量可行步骤或优先级。' },
    ].map((t) => ({
      ...t,
      asrModelId: 'ASR_Qwen3ASRRealtime', vadModelId: 'VAD_SileroVAD', llmModelId: 'LLM_QwenPlusOfficial', vllmModelId: 'VLLM_QwenVLVLLM',
      ttsModelId: 'TTS_QwenAudioTTSPlus', ttsVoiceId: 'TTS_QwenAudioTTSPlus_0001', memModelId: 'Memory_mem_local_short', intentModelId: 'Intent_function_call',
      functions: [],
    })),

    // 声纹：agentId 是录入时引用的智能体；userId 是“人员身份”里的成员（可为空）
    voicePrints: [
      { id: 'demo-vp-1', agentId: 'demo-a-1', audioId: 'demo-audio-1001', sourceName: '妈妈（演示）', introduce: '家里做饭的人（演示）', userId: null, createDate: at(9 * DAY) },
      { id: 'demo-vp-2', agentId: 'demo-a-1', audioId: 'demo-audio-1005', sourceName: '小林（演示）', introduce: '', userId: null, createDate: at(4 * DAY) },
    ],
  };
}

seed(buildAgentExtraSeed);
