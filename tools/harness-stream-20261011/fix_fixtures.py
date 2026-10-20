from pathlib import Path
S=Path(__file__).parent
p=S/'bootstrap.py';s=p.read_text();needle="    assert llm['model_name']=='qwen3.7-plus'"
if 'persona_device_config' not in s:
 s=s.replace(needle,"    persona_device_config=json.loads((private/'device-config.json').read_text())\n    for key in ('prompt','device_custom_name'):\n        if persona_device_config.get(key):cfg[key]=persona_device_config[key]\n"+needle)
p.write_text(s)
p=S/'wire_conversation.py';s=p.read_text();needle='  c.device_id=old.device_id;'
if 'c.change_system_prompt' not in s:s=s.replace(needle,"  from bootstrap import system_prompt\n  c.change_system_prompt(system_prompt(cfg))\n"+needle)
p.write_text(s)
p=S/'stateful_device.py';s=p.read_text()
if "if 'memory_add' in all_function_registry:" not in s:s=s.replace("        self.tools['memory_add']=ToolDefinition", "        if 'memory_add' in all_function_registry:self.tools['memory_add']=ToolDefinition")
p.write_text(s)
print('persona applied through production prompt entry; baseline supports old registry')
