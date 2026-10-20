"""Offline policy check: default keeps local recall and cannot call cloud."""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

here = Path(__file__).parent
code = here/'voice' if (here/'voice').is_dir() else here

def package(name):
    module=types.ModuleType(name)
    module.__path__=[]
    sys.modules[name]=module

for name in ('core','core.utils','core.providers','core.providers.memory',
             'core.providers.memory.bailian','config'):
    package(name)

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

identity=load('core.utils.person_identity',code/'core/utils/person_identity.py')
base=types.ModuleType('core.providers.memory.base')
class MemoryProviderBase:
    def __init__(self,config):
        self.config=config
        self.short_memory=''
base.MemoryProviderBase=MemoryProviderBase
sys.modules[base.__name__]=base
provider_module=load('core.providers.memory.bailian.bailian',code/'core/providers/memory/bailian/bailian.py')

def actor(mode,status,person,generation):
    return identity.PersonTurn('account',person,generation,1,mode,status,'turn','device','agent',1)

default=actor('default','default','default-person',1)
matched=actor('personal','matched','real-person',0)
unknown=actor('personal','unknown','',0)
assert default.eligible and not default.cloud_eligible
assert matched.eligible and matched.cloud_eligible
assert not unknown.cloud_eligible

provider=provider_module.MemoryProvider({})
provider.short_memory='默认身份的本地摘要'
conn=types.SimpleNamespace(memory=provider,config={})
token=identity.activate(conn,default)
try:
    provider.record_turn(conn,default,'only local')
    assert asyncio.run(provider.background(conn))=='默认身份的本地摘要'
    assert asyncio.run(provider.search(conn,'question'))['status']=='identity_unknown'
    assert asyncio.run(provider.override(conn,'forget','old'))['status']=='identity_unknown'

    api_module=types.ModuleType('config.manage_api_client')
    class ManageApiClient:
        def __init__(self,config):pass
        async def request(self,*args,**kwargs):
            assert args[1]=='person-memory/internal/recent'
            return {'status':'ok','reliable':True,'text':'最近的本地对话'}
    api_module.ManageApiClient=ManageApiClient
    sys.modules[api_module.__name__]=api_module
    recent=load('core.utils.recent_memory',code/'core/utils/recent_memory.py')
    async def cloud_forbidden(*args):raise AssertionError('default_cloud_search')
    provider.search=cloud_forbidden
    result=asyncio.run(recent.search(conn,'question'))
    assert result['source']=='local' and result['text']=='最近的本地对话'
finally:
    identity.deactivate(token)

print('default_local_only_policy_passed')
