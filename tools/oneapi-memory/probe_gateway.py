"""Verify the published gateway with synthetic data; never emits API keys."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from probe_upstream import mysql

BASE = 'https://api.realecho.cn/bailian/api/v2/apps/memory/'


def call(method, path, key=None, payload=None, origin=None):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer sk-' + key
    if origin:
        headers['Origin'] = origin
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(BASE + path, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=100) as response:
            status, raw = response.status, response.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(8192)
    decoded = json.loads(raw)
    return status, decoded


def report(operation, result):
    status, data = result
    print(json.dumps({'operation': operation, 'http_status': status,
                      'request_id': data.get('request_id'),
                      'plan_version': data.get('plan_version'),
                      'node_count': len(data.get('memory_nodes', [])),
                      'total': data.get('total'),
                      'code': data.get('code') or data.get('error', {}).get('code')}), flush=True)


def main():
    credentials = mysql("""SELECT JSON_OBJECT('key',t.`key`,'role',u.role)
      FROM one_api.tokens t JOIN one_api.users u ON u.id=t.user_id
      WHERE t.status=1 AND u.status=1 AND (t.expired_time=-1 OR t.expired_time>UNIX_TIMESTAMP())
      AND COALESCE(t.subnet,'')='' ORDER BY u.role DESC,t.id ASC;""")
    admin = next((row['key'] for row in credentials if row['role'] >= 10), None)
    ordinary = next((row['key'] for row in credentials if row['role'] < 10), None)
    if not admin:
        raise SystemExit('No existing backend administrator token available; no token created.')
    probe_user = 'gateway_connectivity_' + uuid.uuid4().hex
    query = 'memory_nodes?' + urllib.parse.urlencode({'user_id': probe_user, 'page_num': 1, 'page_size': 100})
    cleanup = {'user_id': probe_user, 'node_ids': []}
    failures = []
    try:
        result = call('GET', query)
        report('unauthenticated_rejected', result)
        if result[0] != 401:
            failures.append('unauthenticated access')
        if ordinary:
            result = call('GET', query, ordinary)
            report('ordinary_account_rejected', result)
            if result[0] != 403:
                failures.append('ordinary account access')
        result = call('GET', query, admin, origin='https://browser.invalid')
        report('browser_rejected', result)
        if result[0] != 403:
            failures.append('browser access')
        result = call('GET', query, admin)
        report('list_empty_synthetic_user', result)
        if result[0] != 200 or result[1].get('total', 0) != 0:
            raise RuntimeError('Synthetic identity did not start empty')
        result = call('POST', 'add', admin, {'user_id': probe_user,
                     'custom_content': '网关连通性测试用临时标记：' + probe_user + '。不是真实用户资料。'})
        report('write_synthetic_memory', result)
        if result[0] != 200:
            failures.append('write')
        cleanup['node_ids'].extend(node['memory_node_id'] for node in result[1].get('memory_nodes', []) if node.get('memory_node_id'))
        search_payload = {
            'user_id': probe_user, 'messages': [{'role': 'user', 'content': '网关连通性测试用临时标记：' + probe_user}],
            'plan_version': 'lite', 'top_k': 5}
        result = call('POST', 'memory_nodes/search', admin, search_payload)
        report('search_lite_synthetic_memory', result)
        for _ in range(10):
            if result[0] != 200 or result[1].get('memory_nodes') or not cleanup['node_ids']:
                break
            time.sleep(3)
            result = call('POST', 'memory_nodes/search', admin, search_payload)
            report('search_lite_after_wait', result)
        if result[0] != 200 or result[1].get('plan_version') != 'lite' or not result[1].get('memory_nodes'):
            failures.append('lite search')
        for node_id in cleanup['node_ids']:
            result = call('GET', 'memory_nodes/' + node_id, admin)
            report('get_synthetic_node', result)
            if result[0] != 200:
                failures.append('get node')
        result = call('GET', 'profile_schemas?page_size=1&page_num=1', admin)
        report('list_profile_templates', result)
        if result[0] != 200:
            failures.append('profile templates')
    finally:
        # Only nodes belonging to the randomly generated synthetic identity.
        # List again also catches writes committed before a client timeout.
        for attempt in range(3):
            result = call('GET', query, admin)
            report('list_cleanup_candidates', result)
            if result[0] != 200:
                failures.append('cleanup listing')
                break
            ids = set(cleanup['node_ids']) | {node['memory_node_id'] for node in result[1].get('memory_nodes', [])}
            for node_id in ids:
                result = call('DELETE', 'memory_nodes/' + urllib.parse.quote(node_id, safe=''), admin)
                report('delete_synthetic_node', result)
                if result[0] not in (200, 204, 404):
                    failures.append('cleanup deletion')
            cleanup['node_ids'] = []
            result = call('GET', query, admin)
            report('confirm_synthetic_cleanup', result)
            if result[0] == 200 and result[1].get('total') == 0:
                break
            if attempt < 2:
                time.sleep(2)
        else:
            failures.append('synthetic records still present')
    if failures:
        raise SystemExit('FAILED: ' + ', '.join(failures))
    print('PASS: published native gateway read/write/search/delete; synthetic memory cleaned; auth enforced', flush=True)


if __name__ == '__main__':
    main()
