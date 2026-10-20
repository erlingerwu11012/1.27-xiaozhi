import json,pathlib
p=pathlib.Path('/root/prjs/tmp/harness-20261007/frozen-20261008-budget-delta');d=json.loads((p/'full-message-evidence.json').read_text());print([{'keys':list(x),'passed':x.get('passed'),'checks':x.get('checks'),'id':x.get('id')} for x in d])
