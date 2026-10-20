"""Check Search on existing Alibaba channels using a nonexistent synthetic user."""
import json
import urllib.error
import urllib.request
import uuid

from probe_upstream import mysql


for channel in mysql("SELECT JSON_OBJECT('id',id,'key',`key`) FROM one_api.channels WHERE type=17 AND status=1 ORDER BY id;"):
    body = {'user_id': 'permission_probe_' + uuid.uuid4().hex,
            'messages': [{'role': 'user', 'content': '网关连通性检查'}],
            'top_k': 1, 'plan_version': 'lite'}
    request = urllib.request.Request('https://dashscope.aliyuncs.com/api/v2/apps/memory/memory_nodes/search',
              method='POST', data=json.dumps(body, ensure_ascii=False).encode(),
              headers={'Authorization': 'Bearer ' + channel['key'].strip(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, raw = response.status, response.read(16384)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(16384)
    data = json.loads(raw)
    print(json.dumps({'channel_id': channel['id'], 'operation': 'search_lite', 'http_status': status,
                      'code': data.get('code'), 'message': data.get('message'), 'request_id': data.get('request_id')}))
