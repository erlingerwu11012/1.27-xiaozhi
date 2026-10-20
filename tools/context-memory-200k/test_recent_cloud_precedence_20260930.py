"""Host test for on-demand cloud fallback with misleading local question hits."""
from pathlib import Path
import asyncio
import importlib.util
import sys
import types

root = Path('/root/prjs/tmp/context-memory-release-20260929/directory-schema-20260930')
actor = types.SimpleNamespace(eligible=True, payload=lambda: {})
identity = types.ModuleType('core.utils.person_identity')
identity.current_turn = lambda conn: conn.actor
sys.modules['core'] = types.ModuleType('core')
sys.modules['core.utils'] = types.ModuleType('core.utils')
sys.modules['core.utils.person_identity'] = identity
config = types.ModuleType('config')
manager = types.ModuleType('config.manage_api_client')

class Client:
    def __init__(self, configuration):
        self.configuration = configuration

    async def request(self, *args, **kwargs):
        return self.configuration['local']

manager.ManageApiClient = Client
sys.modules['config'] = config
sys.modules['config.manage_api_client'] = manager
spec = importlib.util.spec_from_file_location('recent_memory_staged', root / 'recent_memory.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Provider:
    def __init__(self, response, personal=True):
        self.response = response
        self.personal = personal
        self.calls = 0

    async def search(self, conn, query):
        self.calls += 1
        return self.response

async def check():
    question_hit = {'status': 'ok', 'reliable': True,
                    'text': '[用户] 小台灯叫什么？ [助手] 没有记录'}
    fact = {'status': 'ok', 'text': '小台灯叫晨星灯'}
    conn = types.SimpleNamespace(actor=actor, config={'local': question_hit},
                                 memory=Provider(fact))
    result = await module.search(conn, '小台灯叫什么？')
    assert result['source'] == 'cloud' and '晨星灯' in result['text']
    assert conn.memory.calls == 1
    conn.memory = Provider({'status': 'ok', 'text': ''})
    result = await module.search(conn, '小台灯叫什么？')
    assert result['source'] == 'local' and conn.memory.calls == 1
    conn.config['local'] = {'status': 'suppressed', 'reliable': False, 'text': ''}
    conn.memory = Provider(fact)
    result = await module.search(conn, '小台灯叫什么？')
    assert result['source'] == 'local' and conn.memory.calls == 0
    conn.config['local'] = question_hit
    conn.memory = Provider(fact, personal=False)
    result = await module.search(conn, '小台灯叫什么？')
    assert result['source'] == 'local' and conn.memory.calls == 0
    conn.actor = None
    assert (await module.search(conn, '小台灯叫什么？'))['status'] == 'identity_unknown'
    print({'cloud_precedence': True, 'local_fallback': True,
           'suppression_prevents_cloud': True, 'short_term_zero_cloud': True,
           'unknown_zero_personal_search': True})

asyncio.run(check())
