import ast,pprint
from pathlib import Path
root=Path(__file__).parent/'work/core/utils/tool_harness'
s=(root/'contracts.py').read_text(encoding='utf-8');tree=ast.parse(s);values={}
for node in tree.body:
 if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'READS','WRITES','LABELS','PREREQUISITES','PATTERNS'}:values[node.targets[0].id]=ast.literal_eval(node.value)
 if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute) and isinstance(node.value.func.value,ast.Name) and node.value.func.value.id=='LABELS':
  expression=ast.Expression(node.value.args[0]);values['LABELS'].update(eval(compile(expression,'manifest','eval'),{'__builtins__':{},'dict':dict,'zip':zip}))
 if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Subscript):
  target=node.targets[0]
  if isinstance(target.value,ast.Name) and target.value.id=='LABELS':values['LABELS'][ast.literal_eval(target.slice)]=ast.literal_eval(node.value)
registry=(root/'registry.py').read_text(encoding='utf-8');rvalues={}
for node in ast.parse(registry).body:
 if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in {'PLUGIN','SERVER_MCP'}:rvalues[node.targets[0].id]=ast.literal_eval(node.value)
rows={n:{'source':'server_plugin' if n in rvalues['PLUGIN'] else 'server_mcp' if n in rvalues['SERVER_MCP'] else 'device_mcp',
 'write':n in values['WRITES'],'prerequisites':values['PREREQUISITES'].get(n,[]),
 'label':values['LABELS'].get(n,n),'receipt_checker':n,'receipt_pattern':values['PATTERNS'].get(n)} for n in sorted(values['READS']|values['WRITES'])}
(root/'declarations.py').write_text('"""Single audited capability declarations; live MCP Schema is joined by registry.manifest."""\nDECLARATIONS='+pprint.pformat(rows,width=110,sort_dicts=False)+'\n',encoding='utf-8')
a=s.index('READS={');b=s.index('@dataclass',a)
s=s[:a]+'''from .declarations import DECLARATIONS
READS={n for n,d in DECLARATIONS.items() if not d['write']}
WRITES={n for n,d in DECLARATIONS.items() if d['write']}
LABELS={n:d['label'] for n,d in DECLARATIONS.items()}
PREREQUISITES={n:d['prerequisites'] for n,d in DECLARATIONS.items() if d['prerequisites']}
PATTERNS={n:d['receipt_pattern'] for n,d in DECLARATIONS.items() if d['receipt_pattern']}

'''+s[b:];(root/'contracts.py').write_text(s,encoding='utf-8')
registry=registry.replace("from .contracts import contract","from .contracts import contract\nfrom .declarations import DECLARATIONS")
registry=registry.replace("expected='server_plugin' if name in PLUGIN else 'server_mcp' if name in SERVER_MCP else 'device_mcp'","expected=DECLARATIONS.get(name,{}).get('source')")
registry=registry.replace("'completion_adapter':name if c.known else None","'completion_adapter':DECLARATIONS.get(name,{}).get('receipt_checker')")
(root/'registry.py').write_text(registry,encoding='utf-8')
print('unified declarations generated',len(rows))
