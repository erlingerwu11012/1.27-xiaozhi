"""Read-only Bailian credential probe. Never prints credentials or memory content."""
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid


def mysql(query):
    command = ["docker", "exec", "-i", "xiaozhi-esp32-server-db", "sh", "-c",
               'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
    result = subprocess.run(command, input=query, text=True, capture_output=True, check=True)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def main():
    channels = mysql("SELECT JSON_OBJECT('id',id,'key',`key`) FROM one_api.channels WHERE type=17 AND status=1 ORDER BY id;")
    probe_user = "gw_permission_probe_" + uuid.uuid4().hex[:24]
    urls = [
        ("list_memory", "https://dashscope.aliyuncs.com/api/v2/apps/memory/memory_nodes?" +
         urllib.parse.urlencode({'user_id': probe_user, 'page_size': 1, 'page_num': 1})),
        ("list_profile_schemas", "https://dashscope.aliyuncs.com/api/v2/apps/memory/profile_schemas?page_size=1&page_num=1"),
    ]
    for channel in channels:
        for operation, url in urls:
            request = urllib.request.Request(url, headers={"Authorization": "Bearer " + channel['key'].strip()})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    status, raw = response.status, response.read(1024 * 1024)
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read(8192)
            except Exception as exc:
                print(json.dumps({'channel_id': channel['id'], 'operation': operation, 'transport_error': type(exc).__name__}))
                continue
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                data = {}
            print(json.dumps({'channel_id': channel['id'], 'operation': operation,
                              'http_status': status, 'code': data.get('code'),
                              'request_id': data.get('request_id'),
                              'response_fields': sorted(data.keys()) if isinstance(data, dict) else []}))


if __name__ == '__main__':
    main()
