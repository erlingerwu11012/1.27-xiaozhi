/**
 * 字典（/admin/dict/*）—— 按类型读取字典数据（固件类型、手机区号等），普通用户页面也会用到。
 * 字典类型 / 字典数据的管理接口由同一文件后续补充。
 */
import { route, ok } from '../core';

route('GET', '/admin/dict/data/type/:dictType', ({ params, db }) => ok((db.dictByType[params.dictType] || []).map((x) => ({ ...x }))));
