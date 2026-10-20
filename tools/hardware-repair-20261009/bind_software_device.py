import json,sys,pymysql,requests
from pathlib import Path
S=Path(__file__).parent;e=json.loads((S/'private-test-env.json').read_text());headers={'Authorization':'Bearer '+(S/'api-test-secret').read_text()}
info=requests.get('http://127.0.0.1:18002/xiaozhi/user-identities/internal/state/99003',headers=headers,timeout=3).json()['data']
db=pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True)
assert e['PERSON_MEMORY_TEST_DATABASE']=='bailian_memory_test_experience_20261009'
with db.cursor() as c:c.execute("INSERT INTO ai_device(id,user_id,mac_address,agent_id) VALUES('software-device-test',99003,'SOFTWARE-DEVICE-ONLY','agent_http') ON DUPLICATE KEY UPDATE user_id=99003,agent_id='agent_http'")
print('synthetic software device bound to isolated test account')
