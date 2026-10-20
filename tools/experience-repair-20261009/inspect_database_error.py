from pathlib import Path
p=Path(__file__).parent/'prepare_database.py';s=p.read_text(encoding='utf-8-sig').replace("if proc.returncode:raise RuntimeError('isolated_schema_import_failed')","if proc.returncode:raise RuntimeError('isolated_schema_import_failed:'+proc.stderr.decode(errors='replace')[:700])");p.write_text(s,encoding='utf-8')
