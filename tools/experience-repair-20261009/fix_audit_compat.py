from pathlib import Path
p=Path(__file__).parent/'memory_quarantine.py';s=p.read_text(encoding='utf-8-sig');s=s.replace("   c.execute('SELECT * FROM '+table+' WHERE recall_allowed=TRUE')", "   c.execute('SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=\'recall_allowed\'',(table,))\n   has_flag=bool(c.fetchone()['n'])\n   c.execute('SELECT * FROM '+table+(' WHERE recall_allowed=TRUE' if has_flag else ''))")
p.write_text(s,encoding='utf-8')
