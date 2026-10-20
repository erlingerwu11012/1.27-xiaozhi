import asyncio,json,sys
sys.path.insert(0,'/root/prjs/tmp/harness-20261007')
from rollout import health
print(json.dumps(asyncio.run(health(internal_port=8006,public=True))))
