import pathlib,re,json
roots=[pathlib.Path('/root/prjs/xiaozhi_mcp_gateway'),pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/manager-api/src/main/resources')]
found=[]
for root in roots:
 for p in root.rglob('*'):
  if not p.is_file() or p.suffix not in {'.py','.yml','.yaml','.json','.properties','.env','.conf'} or any(n in p.parts for n in ['node_modules','.git','target','venv','.venv']):continue
  if p.stat().st_size>2000000:continue
  text=p.read_text(errors='replace')
  for port in ['8000','8003','8006']:
   if re.search(r'(?:127\.0\.0\.1|localhost):'+port+r'\b',text):found.append({'file':str(p),'legacy_local_port':port})
print(json.dumps({'legacy_local_port_references':found},ensure_ascii=False))
