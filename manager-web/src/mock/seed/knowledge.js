/**
 * 知识库（/datasets*）、记忆（/admin/memory*）、习惯（/habits*）的初始演示数据。
 *
 * - 知识库、文档名称都带“演示”；切片内容以“（演示切片）”开头，是写死的示例文字，不来自任何真实文件。
 * - 记忆内容一律以“（演示）”开头，不含真实个人信息。
 * - 设备 id 引用 seed/core.js 的 demo-d-1 / demo-d-2 / demo-d-3 / demo-d-9。
 *
 * 已经保存在浏览器里的旧演示数据库没有这些字段，handlers 里用 ensureKnowledge / ensureMemory / ensureHabits 补齐。
 */
import { seed, nowStr } from '../core';
import { DEMO_USERS } from './core';

const daysAgo = (d, h = 10) => nowStr(new Date(Date.now() - d * 86400000 - h * 3600000));

/** 默认检索模型：模型配置里没有 RAG 类型的模型时使用 */
export const DEFAULT_RAG_MODELS = [
  { id: 'RAG_Default', modelName: '默认知识库检索（演示）' },
];

const chunk = (datasetId, documentId, index, content) => ({
  id: `${documentId}-c${index + 1}`, datasetId, documentId, index, content,
});

export function buildKnowledge() {
  const U = DEMO_USERS.user.id;
  const A = DEMO_USERS.admin.id;
  const datasets = [
    { id: 'kb-1', datasetId: 'ds-demo-0001', userId: U, name: '演示-产品使用手册', description: '（演示）小念桌面版的开机、联网、绑定和常用设置说明，回答设备使用类问题时参考。', status: 1, ragModelId: 'RAG_Default', createdAt: daysAgo(20) },
    { id: 'kb-2', datasetId: 'ds-demo-0002', userId: U, name: '演示-家庭常见问题', description: '（演示）家里人经常问到的作息、提醒和设备使用问题。', status: 1, ragModelId: 'RAG_Default', createdAt: daysAgo(9) },
    { id: 'kb-3', datasetId: 'ds-demo-0003', userId: U, name: '演示-读书笔记', description: '（演示）还没有上传文档的知识库，暂未启用。', status: 0, ragModelId: 'RAG_Default', createdAt: daysAgo(2) },
    { id: 'kb-9', datasetId: 'ds-demo-0009', userId: A, name: '演示-联调知识库', description: '（演示）管理员账号下用于检查检索效果的知识库。', status: 1, ragModelId: 'RAG_Default', createdAt: daysAgo(40) },
  ];
  const documents = [
    { id: 'doc-101', datasetId: 'ds-demo-0001', name: '（演示）快速上手指南.pdf', size: 482113, type: 'application/pdf', createdAt: daysAgo(19), parseStatusCode: 3, progress: 1 },
    { id: 'doc-102', datasetId: 'ds-demo-0001', name: '（演示）联网与绑定说明.docx', size: 126554, type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', createdAt: daysAgo(18), parseStatusCode: 3, progress: 1 },
    { id: 'doc-103', datasetId: 'ds-demo-0001', name: '（演示）常见故障排查.md', size: 18320, type: 'text/markdown', createdAt: daysAgo(3), parseStatusCode: 0, progress: 0 },
    { id: 'doc-104', datasetId: 'ds-demo-0001', name: '（演示）旧版说明书.pdf', size: 0, type: 'application/pdf', createdAt: daysAgo(15), parseStatusCode: 4, progress: 0, failReason: '文件内容为空' },
    { id: 'doc-201', datasetId: 'ds-demo-0002', name: '（演示）家庭问答.txt', size: 9214, type: 'text/plain', createdAt: daysAgo(8), parseStatusCode: 3, progress: 1 },
    { id: 'doc-202', datasetId: 'ds-demo-0002', name: '（演示）提醒设置说明.csv', size: 4210, type: 'text/csv', createdAt: daysAgo(0, 1), parseStatusCode: 1, progress: 0.4, _pollsLeft: 2 },
    { id: 'doc-901', datasetId: 'ds-demo-0009', name: '（演示）联调检查清单.md', size: 6120, type: 'text/markdown', createdAt: daysAgo(39), parseStatusCode: 3, progress: 1 },
  ];
  const chunks = [
    ...[
      '（演示切片）开机：长按设备顶部按键约 3 秒，指示灯亮起后松开。首次开机会进入联网模式，并播报“请连接热点”。',
      '（演示切片）联网：用手机连接设备发出的热点，在弹出的页面里选择家里的 Wi-Fi 并输入密码。设备联网成功后会播报 6 位验证码。',
      '（演示切片）绑定：在控制台的“添加设备”里输入设备播报的 6 位验证码，选择要绑定的智能体，点“绑定”。',
      '（演示切片）音量：对设备说“大声一点”或“小声一点”调节音量；也可以按侧边的音量键。',
      '（演示切片）唤醒：默认唤醒词是“你好小念”。唤醒后指示灯变为常亮，说完话停顿一会儿，设备会自动开始回答。',
      '（演示切片）休眠：一段时间没有对话，设备会自动进入待机，指示灯熄灭；再次唤醒即可继续使用。',
    ].map((t, i) => chunk('ds-demo-0001', 'doc-101', i, t)),
    ...[
      '（演示切片）更换 Wi-Fi：长按按键 10 秒恢复联网模式，再按“联网”步骤重新连接。已绑定的智能体不会丢失。',
      '（演示切片）验证码过期：验证码 5 分钟内有效。过期后对设备说“重新播报验证码”即可获得新的验证码。',
      '（演示切片）解绑：在控制台的设备管理里点“解绑”。解绑后设备需要重新输入验证码才能绑定到其他智能体。',
      '（演示切片）多台设备：一个智能体可以绑定多台设备，它们共用同一套角色设定和记忆设置。',
    ].map((t, i) => chunk('ds-demo-0001', 'doc-102', i, t)),
    ...[
      '（演示切片）问：设备每天几点提醒喝水？答：在习惯里设置的时间提醒，默认提前 2 分钟播报。',
      '（演示切片）问：晚上不想被打扰怎么办？答：对设备说“开启勿扰”，到第二天早上会自动关闭。',
      '（演示切片）问：孩子能自己和设备聊天吗？答：可以，建议在角色设定里写明说话方式和需要回避的话题。',
      '（演示切片）问：设备能讲故事吗？答：可以，说“讲一个睡前故事”即可，故事长度可以在对话里要求。',
      '（演示切片）问：天气播报的城市怎么改？答：在智能体的插件设置里修改天气查询的默认城市。',
    ].map((t, i) => chunk('ds-demo-0002', 'doc-201', i, t)),
    ...[
      '（演示切片）联调检查：确认设备固件版本、绑定状态和最后对话时间是否与控制台一致。',
      '（演示切片）检索效果：用三到五个常见问题做召回测试，观察排在前面的切片是否回答了问题。',
    ].map((t, i) => chunk('ds-demo-0009', 'doc-901', i, t)),
  ];
  return { kbDatasets: datasets, kbDocuments: documents, kbChunks: chunks };
}

/** 记忆类别与原页面一致：personal / preference / work / relationship / general */
export function buildMemory() {
  const rows = [
    ['demo-d-1', 'preference', '（演示）用户喜欢早上喝咖啡'],
    ['demo-d-1', 'preference', '（演示）用户听歌偏爱轻音乐'],
    ['demo-d-1', 'general', '（演示）用户每天晚上十点左右准备休息'],
    ['demo-d-1', 'personal', '（演示）用户希望被称呼为“同桌”'],
    ['demo-d-1', 'work', '（演示）用户这周在准备一次项目汇报'],
    ['demo-d-1', 'relationship', '（演示）用户提到家里养了一只猫'],
    ['demo-d-1', 'general', '（演示）用户习惯午饭后散步十分钟'],
    ['demo-d-1', 'preference', '（演示）用户不喜欢太长的回答'],
    ['demo-d-1', 'work', '（演示）用户周一上午通常有例会'],
    ['demo-d-1', 'preference', '（演示）用户喜欢听天气播报时带上穿衣建议'],
    ['demo-d-2', 'general', '（演示）用户睡前会听一会儿故事'],
    ['demo-d-2', 'preference', '（演示）用户喜欢温和、语速慢一点的声音'],
    ['demo-d-2', 'personal', '（演示）用户在学习弹吉他'],
    ['demo-d-2', 'relationship', '（演示）用户周末常和朋友去爬山'],
    ['demo-d-2', 'general', '（演示）用户早上七点起床'],
    ['demo-d-2', 'work', '（演示）用户最近在整理书房'],
    ['demo-d-3', 'preference', '（演示）用户喜欢在睡前听白噪音'],
    ['demo-d-3', 'general', '（演示）用户周末会晚一点起床'],
    ['demo-d-3', 'personal', '（演示）用户正在练习早睡'],
    ['demo-d-3', 'relationship', '（演示）用户提到下周有朋友来家里做客'],
    ['demo-d-3', 'preference', '（演示）用户喜欢简短的晚安问候'],
    ['demo-d-9', 'work', '（演示）测试账号用于检查记忆提取效果'],
    ['demo-d-9', 'general', '（演示）测试账号每天下午做一次联调'],
    ['demo-d-9', 'preference', '（演示）测试账号要求回答控制在两句话以内'],
  ];
  const memories = rows.map(([device, category, fact], i) => {
    const t = nowStr(new Date(Date.now() - (i * 7 + 3) * 3600000));
    return { id: 5001 + i, device_id: device, category, fact, created_at: t, updated_at: t };
  });
  return { memories };
}

/**
 * 习惯：syncState 取值与原页面 statusText 一致（needs_binding / pending / upgrade_required / failed / synced），
 * syncError 取值也来自原页面的原因表。enabled=0 表示已删除（软删除）。
 */
export function buildHabits() {
  const A = DEMO_USERS.admin.id;
  const U = DEMO_USERS.user.id;
  const h = (o) => Object.assign({ advanceMinutes: 2, source: 'manual', enabled: 1, syncState: 'synced', syncError: '', recipientPersonId: 'all' }, o);
  const habits = [
    h({ id: 701, userId: A, description: '（演示）喝水', hour: 10, minute: 0, deviceId: 'demo-d-9', createdAt: daysAgo(14) }),
    h({ id: 702, userId: A, description: '（演示）午休', hour: 13, minute: 0, advanceMinutes: 5, deviceId: 'demo-d-9', recipientPersonId: 'demo-p-1', createdAt: daysAgo(10) }),
    h({ id: 703, userId: A, description: '（演示）傍晚散步', hour: 18, minute: 30, advanceMinutes: 10, deviceId: 'demo-d-9', syncState: 'failed', syncError: 'device_offline', createdAt: daysAgo(6) }),
    h({ id: 704, userId: A, description: '（演示）睡前阅读', hour: 21, minute: 30, source: 'auto', deviceId: 'demo-d-9', createdAt: daysAgo(4) }),
    h({ id: 705, userId: A, description: '（演示）早起拉伸', hour: 7, minute: 15, deviceId: '', recipientPersonId: '', syncState: 'needs_binding', createdAt: daysAgo(30) }),
    h({ id: 706, userId: A, description: '（演示）冥想', hour: 22, minute: 0, deviceId: 'demo-d-9', syncState: 'upgrade_required', createdAt: daysAgo(3) }),
    h({ id: 707, userId: A, description: '（演示）晨间新闻', hour: 8, minute: 0, deviceId: 'demo-d-9', enabled: 0, createdAt: daysAgo(25) }),
    h({ id: 711, userId: U, description: '（演示）喝水', hour: 15, minute: 0, deviceId: 'demo-d-1', createdAt: daysAgo(5) }),
  ];
  // 接收人目录（演示）：与人员身份模块的真实数据无关
  const habitPeople = {
    [A]: [{ user_id: 'demo-p-1', display_name: '家人甲（演示）' }, { user_id: 'demo-p-2', display_name: '家人乙（演示）' }],
    [U]: [{ user_id: 'demo-p-11', display_name: '家人（演示）' }],
  };
  return { habits, habitPeople };
}

seed(buildKnowledge);
seed(buildMemory);
seed(buildHabits);
