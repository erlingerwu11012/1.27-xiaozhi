from pathlib import Path
p=Path(__file__).parent/'prepare_database.py';s=p.read_text(encoding='utf-8').replace('import importlib.util,json,os,subprocess','import importlib.util,json,os,subprocess,re').replace("schema=Path('/root/prjs/releases/experience-repair-20261009/backup/schema.sql').read_bytes()","schema=Path('/root/prjs/releases/experience-repair-20261009/backup/schema.sql').read_bytes()\n    schema=re.sub(rb'SET\\s+@@GLOBAL\\.[\\s\\S]*?;',b'',schema,flags=re.I)\n    if b'@@GLOBAL' in schema:raise RuntimeError('global_statement_in_schema')")
p.write_text(s,encoding='utf-8')
