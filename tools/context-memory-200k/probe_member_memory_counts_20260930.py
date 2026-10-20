"""Read-only member memory counts; never reads a fact, transcript, or secret."""
from pathlib import Path
import hashlib
import json
import subprocess

target = json.loads((Path('/root/prjs/tmp/memory-test-20260930') / 'target.json').read_text())
assert target['state']['mode'] == 'personal' and len(target['voice_members']) == 1
account = int(target['account_id'])
person = target['voice_members'][0]['person_id']
owner = None
mysql = ['docker', 'exec', '-i', 'xiaozhi-esp32-server-db', 'sh', '-c',
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']

def sql(query):
    return subprocess.run(mysql, input=query, text=True, capture_output=True,
                          check=True).stdout.strip()

def literal(value):
    return "CONVERT(X'" + str(value).encode().hex() + "' USING utf8mb4)"

owner = int(sql('SELECT oneapi_user_id FROM xiaozhi_esp32_server.sys_user_oneapi_binding '
                'WHERE sys_user_id=%d;' % account))
cloud = 're_' + hashlib.sha256(('%d:%d:%s:0' % (owner, account, person)).encode()).hexdigest()[:60]
scope = 'account_id=%d AND user_id=%s AND generation=0' % (account, literal(person))
materials = int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material WHERE ' + scope + ';'))
tasks = sql('SELECT state,COUNT(*) FROM xiaozhi_esp32_server.ai_memory_task WHERE '
            + scope + ' GROUP BY state;')
entity = sql('SELECT state,daily_watermark>processed_watermark FROM '
             'xiaozhi_esp32_server.ai_person_memory_entity WHERE ' + scope + ';')
charges = sql('SELECT operation,state,COUNT(*) FROM one_api.memory_charges WHERE '
              'BINARY cloud_user_id=BINARY ' + literal(cloud) + ' GROUP BY operation,state;')
archive = sql('SELECT identity_status,COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_history '
              'WHERE account_id=%d AND person_id=%s GROUP BY identity_status;' % (account, literal(person)))
print(json.dumps({'material_count': materials, 'task_groups': tasks.splitlines(),
                  'entity': entity.splitlines(), 'charge_groups': charges.splitlines(),
                  'archive_groups': archive.splitlines()}, ensure_ascii=False))
