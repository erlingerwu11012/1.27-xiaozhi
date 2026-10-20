"""Read the backed-up device settings and inspect a bootstrap response without logging credentials."""
from pathlib import Path
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

STAGE = Path(__file__).parent
sys.path.insert(0, 'E:/Espressif/frameworks/esp-idf-v5.5.4/components/nvs_flash/nvs_partition_tool')
from nvs_parser import NVS_Partition

def read_saved_settings():
    meta = json.loads((STAGE / 'evidence/device-preflight.json').read_text(encoding='utf-8'))
    partition = NVS_Partition('nvs', bytearray((Path(meta['backup']) / 'nvs.bin').read_bytes()))
    entries = [entry for page in sorted(partition.pages, key=lambda p: p.header['page_index'])
               if not page.is_empty for entry in page.entries if entry.state == 'Written' and entry.key]
    namespaces = {entry.data['value']: entry.key for entry in entries if entry.metadata['namespace'] == 0}
    values = {}
    for entry in entries:
        if entry.metadata['type'] == 'string':
            value = b''.join(bytes(child.raw) for child in entry.children)[:entry.data['size']]
            value = value.rstrip(b'\0').decode('utf-8', 'replace')
        elif entry.metadata['type'] in ('uint8_t', 'int32_t'):
            value = entry.data['value']
        else:
            continue
        values[(namespaces.get(entry.metadata['namespace']), entry.key)] = value
    return meta, values

def main():
    meta, values = read_saved_settings()
    url = values.get(('wifi', 'ota_url')) or 'https://api.realecho.cn/xiaozhi/ota/'
    headers = {'Device-Id': meta['mac'], 'Client-Id': values[('board', 'uuid')],
               'Activation-Version': '1', 'User-Agent': 'esp-box-3/2.0.5', 'Content-Type': 'application/json'}
    key = values.get(('websocket', 'auth_key'))
    if key:
        headers['Authorization'] = 'Bearer ' + key
    body = {'application': {'version': '2.0.5'}, 'board': {'type': 'esp-box-3'}, 'chip_model_name': 'esp32s3'}
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method='POST')
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    raw = response.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    ws = data.get('websocket') or {}
    parsed = urllib.parse.urlsplit(ws.get('url', ''))
    summary = {'http_status': response.status, 'json_keys': sorted(data),
               'activation_present': isinstance(data.get('activation'), dict),
               'websocket_present': isinstance(data.get('websocket'), dict),
               'mqtt_present': isinstance(data.get('mqtt'), dict),
               'websocket_url': parsed.scheme + '://' + str(parsed.hostname) + parsed.path if parsed.hostname else '',
               'token_present': bool(ws.get('token')), 'auth_key_present': bool(ws.get('auth_key')),
               'saved_auth_key_length': len(key or '')}
    for field in ('code', 'status', 'error'):
        if field in data and isinstance(data[field], (str, int, bool)):
            summary[field] = str(data[field])[:160]
    (STAGE / 'evidence/ota-bootstrap-diagnostic.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))

if __name__ == '__main__':
    main()
