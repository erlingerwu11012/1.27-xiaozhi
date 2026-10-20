/**
 * 知识库（/datasets*）与检索模型选项（GET /datasets/rag-models，属于 model.js 的 API 模块）。
 *
 * 响应结构按调用方读取的字段编写：
 * - 列表：res.data.data.list / res.data.data.total（KnowledgeBaseManagement、KnowledgeFileUpload）；
 * - 文档：id / name / createdAt / parseStatusCode（0 未开始、1 处理中、2 已取消、3 已完成、4 失败）；
 * - 切片：data.data.list / data.data.total，切片项读 content；
 * - 召回测试：data.data.chunks[]，读 content / similarity。
 *
 * 演示规则：上传只记录文件名、大小和类型，不读取、不保存文件内容；文档上传后为“未开始”，
 * 点“解析”后进入“处理中”，在之后的列表刷新（页面每 5 秒轮询一次）中推进到“已完成”，并生成写死的演示切片。
 * 空文件（0 字节）解析会失败，用于演示失败状态。
 */
import { route, ok, fail, nowStr, nextId, paginate, includesText } from '../core';
import { buildKnowledge, DEFAULT_RAG_MODELS } from '../seed/knowledge';

const ACCEPT_EXT = ['doc', 'docx', 'pdf', 'txt', 'md', 'mdx', 'csv', 'xls', 'xlsx', 'ppt', 'pptx'];
const NAME_RE = /^[一-龥a-zA-Z0-9\s\-_]+$/;

function ensure(db) {
  if (!db.kbDatasets || !db.kbDocuments || !db.kbChunks) Object.assign(db, buildKnowledge());
  return db;
}

function ragModels(db) {
  const configured = (db.models || []).filter((m) => m.modelType === 'RAG' && m.isEnabled === 1)
    .map((m) => ({ id: m.id, modelName: m.modelName }));
  return configured.length ? configured : DEFAULT_RAG_MODELS;
}

const ownDataset = (db, user, datasetId) => ensure(db).kbDatasets.find((d) => d.datasetId === datasetId && d.userId === user.id);

function publicDataset(db, d) {
  return {
    id: d.id, datasetId: d.datasetId, name: d.name, description: d.description, status: d.status,
    ragModelId: d.ragModelId, documentCount: db.kbDocuments.filter((x) => x.datasetId === d.datasetId).length,
    createdAt: d.createdAt, updatedAt: d.updatedAt || d.createdAt,
  };
}

function publicDocument(doc) {
  return {
    id: doc.id, name: doc.name, size: doc.size, type: doc.type, createdAt: doc.createdAt,
    parseStatusCode: doc.parseStatusCode, progress: doc.progress || 0,
  };
}

/** 演示切片：只依据文件名生成，明确写明不是文件里的真实内容 */
function demoChunksFor(doc) {
  const base = doc.name.replace(/\.[^.]+$/, '');
  const texts = [
    `（演示切片）这是根据文件《${base}》生成的第 1 段示例内容。演示模式不会读取文件，这里的文字仅用于展示切片效果。`,
    `（演示切片）《${base}》第 2 段示例内容：真实环境中，这里会显示从文档中切分出来的一段原文。`,
    `（演示切片）《${base}》第 3 段示例内容：切片会被用于回答与这份文档相关的问题。`,
  ];
  return texts.map((content, index) => ({ id: `${doc.id}-c${index + 1}`, datasetId: doc.datasetId, documentId: doc.id, index, content }));
}

/** 列表刷新时推进“处理中”的文档 */
function advanceParsing(db, datasetId) {
  db.kbDocuments.filter((d) => d.datasetId === datasetId && d.parseStatusCode === 1).forEach((d) => {
    d._pollsLeft = (d._pollsLeft == null ? 2 : d._pollsLeft) - 1;
    d.progress = Math.min(0.9, (d.progress || 0) + 0.4);
    if (d._pollsLeft > 0) return;
    delete d._pollsLeft;
    if (!d.size) {
      d.parseStatusCode = 4;
      d.progress = 0;
      d.failReason = '文件内容为空';
      return;
    }
    d.parseStatusCode = 3;
    d.progress = 1;
    db.kbChunks = db.kbChunks.filter((c) => c.documentId !== d.id).concat(demoChunksFor(d));
  });
}

/* ───── 检索模型选项 ───── */

route('GET', '/datasets/rag-models', ({ db }) => ok(ragModels(db)));

/* ───── 知识库 ───── */

route('GET', '/datasets', ({ query, db, user, scenario }) => {
  ensure(db);
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const list = db.kbDatasets.filter((d) => d.userId === user.id && includesText(d.name, query.name))
    .sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)))
    .map((d) => publicDataset(db, d));
  return ok(paginate(list, query.page, query.page_size));
});

function validateDataset(db, user, body, selfId) {
  const name = String(body.name || '').trim();
  if (!name) return '请输入知识库名称';
  if (name.length > 50) return '知识库名称长度在 1 到 50 个字符之间';
  if (!NAME_RE.test(name)) return '知识库名称只能包含中文、英文、数字、空格、下划线和连字符';
  if (!String(body.description || '').trim()) return '请输入知识库描述';
  if (String(body.description).length > 300) return '知识库描述不能超过 300 个字符';
  if (db.kbDatasets.some((d) => d.userId === user.id && d.name === name && d.datasetId !== selfId)) return '已有同名知识库，请换一个名称';
  return '';
}

route('POST', '/datasets', ({ body, db, user }) => {
  ensure(db);
  const err = validateDataset(db, user, body);
  if (err) return fail(err);
  if (!body.ragModelId || !ragModels(db).some((m) => m.id === body.ragModelId)) return fail('请选择检索模型');
  const seq = nextId();
  const d = {
    id: `kb-${seq}`, datasetId: `ds-demo-${seq}`, userId: user.id, name: String(body.name).trim(),
    description: String(body.description).trim(), status: body.status === 0 ? 0 : 1, ragModelId: body.ragModelId,
    createdAt: nowStr(),
  };
  db.kbDatasets.push(d);
  return ok(publicDataset(db, d));
});

route('PUT', '/datasets/:datasetId', ({ params, body, db, user }) => {
  const d = ownDataset(db, user, params.datasetId);
  if (!d) return fail('知识库不存在或无权操作');
  // 列表里的启用开关只提交 name / description / status
  const err = validateDataset(db, user, { name: body.name != null ? body.name : d.name, description: body.description != null ? body.description : d.description }, d.datasetId);
  if (err) return fail(err);
  if (body.ragModelId && !ragModels(db).some((m) => m.id === body.ragModelId)) return fail('检索模型不存在');
  if (body.name != null) d.name = String(body.name).trim();
  if (body.description != null) d.description = String(body.description).trim();
  if (body.status != null) d.status = Number(body.status) === 1 ? 1 : 0;
  if (body.ragModelId) d.ragModelId = body.ragModelId;
  d.updatedAt = nowStr();
  return ok(publicDataset(db, d));
});

function removeDatasets(db, ids) {
  db.kbDatasets = db.kbDatasets.filter((d) => !ids.includes(d.datasetId));
  db.kbDocuments = db.kbDocuments.filter((d) => !ids.includes(d.datasetId));
  db.kbChunks = db.kbChunks.filter((c) => !ids.includes(c.datasetId));
}

route('DELETE', '/datasets/batch', ({ query, db, user }) => {
  ensure(db);
  const ids = String(query.ids || '').split(',').map((s) => s.trim()).filter(Boolean);
  if (!ids.length) return fail('请选择要删除的知识库');
  if (ids.some((id) => !ownDataset(db, user, id))) return fail('部分知识库不存在或无权操作');
  removeDatasets(db, ids);
  return ok(null);
});

route('DELETE', '/datasets/:datasetId', ({ params, db, user }) => {
  const d = ownDataset(db, user, params.datasetId);
  if (!d) return fail('知识库不存在或无权操作');
  removeDatasets(db, [d.datasetId]);
  return ok(null);
});

/* ───── 文档 ───── */

route('GET', '/datasets/:datasetId/documents', ({ params, query, db, user, scenario }) => {
  const d = ownDataset(db, user, params.datasetId);
  if (!d) return fail('知识库不存在或无权查看');
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  advanceParsing(db, d.datasetId);
  const list = db.kbDocuments.filter((x) => x.datasetId === d.datasetId && includesText(x.name, query.name))
    .sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)))
    .map(publicDocument);
  return ok(paginate(list, query.page, query.page_size));
});

/** 上传：FormData { file }。只记录文件元数据，文件内容不保存、不发送 */
route('POST', '/datasets/:datasetId/documents', ({ params, body, db, user }) => {
  const d = ownDataset(db, user, params.datasetId);
  if (!d) return fail('知识库不存在或无权操作');
  const f = body.file;
  if (!f || !f.__file) return fail('请选择要上传的文件');
  const ext = String(f.name).split('.').pop().toLowerCase();
  if (!ACCEPT_EXT.includes(ext)) return fail(`不支持的文件类型：.${ext}`);
  if (f.size > 10 * 1024 * 1024) return fail('文件大小不能超过 10MB');
  const doc = {
    id: `doc-${nextId()}`, datasetId: d.datasetId, name: f.name, size: f.size, type: f.type || '',
    createdAt: nowStr(), parseStatusCode: 0, progress: 0,
  };
  db.kbDocuments.push(doc);
  return ok(publicDocument(doc), '已记录文件信息（演示：文件内容没有上传）');
});

route('DELETE', '/datasets/:datasetId/documents/:documentId', ({ params, db, user }) => {
  const d = ownDataset(db, user, params.datasetId);
  if (!d) return fail('知识库不存在或无权操作');
  if (!db.kbDocuments.some((x) => x.id === params.documentId && x.datasetId === d.datasetId)) return fail('文档不存在或已删除');
  db.kbDocuments = db.kbDocuments.filter((x) => x.id !== params.documentId);
  db.kbChunks = db.kbChunks.filter((c) => c.documentId !== params.documentId);
  return ok(null);
});

/** 解析：body { document_ids: [] } */
route('POST', '/datasets/:datasetId/chunks', ({ params, body, db, user }) => {
  const d = ownDataset(db, user, params.datasetId);
  if (!d) return fail('知识库不存在或无权操作');
  const ids = Array.isArray(body.document_ids) ? body.document_ids : [];
  const docs = db.kbDocuments.filter((x) => x.datasetId === d.datasetId && ids.includes(x.id));
  if (!docs.length) return fail('文档不存在或已删除');
  if (docs.some((x) => x.parseStatusCode === 1)) return fail('文档正在解析，请稍候');
  docs.forEach((x) => { x.parseStatusCode = 1; x.progress = 0.1; x._pollsLeft = 2; });
  return ok(null, '已开始解析（演示）');
});

/** 切片列表：?page&page_size&keywords */
route('GET', '/datasets/:datasetId/documents/:documentId/chunks', ({ params, query, db, user }) => {
  const d = ownDataset(db, user, params.datasetId);
  if (!d) return fail('知识库不存在或无权查看');
  const doc = db.kbDocuments.find((x) => x.id === params.documentId && x.datasetId === d.datasetId);
  if (!doc) return fail('文档不存在或已删除');
  const list = db.kbChunks.filter((c) => c.documentId === doc.id && includesText(c.content, query.keywords))
    .sort((a, b) => a.index - b.index)
    .map((c) => ({ id: c.id, content: c.content, document_id: c.documentId, available: true }));
  return ok(paginate(list, query.page, query.page_size));
});

/* ───── 召回测试（演示打分：按问题与切片的字词重合度计算，不是真实向量检索） ───── */

function grams(s) {
  const t = String(s || '').replace(/（演示切片）/g, '').toLowerCase().replace(/[\s，。、：；！？“”‘’（）()《》,.:;!?"'-]/g, '');
  const set = new Set();
  for (let i = 0; i < t.length - 1; i++) set.add(t.slice(i, i + 2));
  if (t.length === 1) set.add(t);
  return set;
}

route('POST', '/datasets/:datasetId/retrieval-test', ({ params, body, db, user }) => {
  const d = ownDataset(db, user, params.datasetId);
  if (!d) return fail('知识库不存在或无权操作');
  const question = String(body.question || '').trim();
  if (!question) return fail('请输入测试问题');
  const q = grams(question);
  const docName = {};
  db.kbDocuments.filter((x) => x.datasetId === d.datasetId).forEach((x) => { docName[x.id] = x.name; });
  const scored = db.kbChunks.filter((c) => c.datasetId === d.datasetId && docName[c.documentId])
    .map((c) => {
      const g = grams(c.content);
      let hit = 0;
      q.forEach((x) => { if (g.has(x)) hit += 1; });
      const term = q.size ? hit / q.size : 0;
      const similarity = Math.min(0.98, 0.18 + term * 0.78);
      return {
        id: c.id, content: c.content, document_id: c.documentId, document_name: docName[c.documentId],
        similarity: Number(similarity.toFixed(4)), term_similarity: Number(term.toFixed(4)),
      };
    })
    .filter((c) => c.term_similarity > 0)
    .sort((a, b) => b.similarity - a.similarity)
    .slice(0, 6);
  return ok({ chunks: scored, total: scored.length }, '召回测试完成（演示结果）');
});
