/**
 * 模型（/models/*）—— 角色配置与创建向导用到的只读选项：模型名称、LLM 列表、音色、插件。
 * 管理员的模型配置（列表、增删改、供应器、默认模型等）由同一文件后续补充。
 */
import { route, ok, fail, includesText } from '../core';

route('GET', '/models/names', ({ query, db }) => ok(
  db.models.filter((m) => m.modelType === query.modelType && m.isEnabled === 1 && includesText(m.modelName, query.modelName))
    .sort((a, b) => (a.sort || 0) - (b.sort || 0))
    .map((m) => ({ id: m.id, modelName: m.modelName })),
));

route('GET', '/models/llm/names', ({ query, db }) => ok(
  db.models.filter((m) => m.modelType === 'LLM' && m.isEnabled === 1 && includesText(m.modelName, query.modelName))
    .map((m) => ({ id: m.id, modelName: m.modelName, type: m.type || 'openai' })),
));

route('GET', '/models/:modelId/voices', ({ params, query, db }) => {
  if (!db.models.some((m) => m.id === params.modelId)) return fail('模型不存在');
  return ok(db.ttsVoices.filter((v) => v.ttsModelId === params.modelId && includesText(v.name, query.voiceName))
    .sort((a, b) => (a.sort || 0) - (b.sort || 0))
    .map((v) => ({ id: v.id, name: v.name, languages: v.languages, voiceDemo: v.voiceDemo || '' })));
});

route('GET', '/models/provider/plugin/names', ({ db }) => ok(db.plugins.map((p) => ({ ...p }))));
