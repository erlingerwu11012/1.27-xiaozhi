"""Print only aggregate counts; never read dialogue or credentials."""
import subprocess

mysql = [
    "docker", "exec", "-i", "xiaozhi-esp32-server-db", "sh", "-c",
    'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names xiaozhi_esp32_server',
]
queries = """
SELECT 'default_active_entities',COUNT(*) FROM ai_person_memory_entity WHERE generation>0 AND state='active';
SELECT 'default_queued_dialogue',COUNT(*) FROM ai_person_material WHERE generation>0 AND kind='dialogue';
SELECT 'default_pending_extract',COUNT(*) FROM ai_memory_task WHERE generation>0 AND kind='extract' AND state IN('pending','retry','submitting','review','accepted');
SELECT 'default_ready_override',COUNT(*) FROM ai_memory_override WHERE generation>0 AND state='ready';
"""
result = subprocess.run(mysql, input=queries, text=True, capture_output=True, check=True)
print(result.stdout, end="")
