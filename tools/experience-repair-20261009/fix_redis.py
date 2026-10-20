from pathlib import Path
p=Path(__file__).parent/'start_api.py';s=p.read_text(encoding='utf-8-sig');a=s.index("subprocess.run(['redis-server'");z=s.index('\nenv=dict',a);s=s[:a]+"subprocess.run(['docker','run','-d','--name','experience-repair-redis','-p','127.0.0.1:16380:6379','redis:latest'],check=True,stdout=subprocess.DEVNULL)"+s[z:];p.write_text(s,encoding='utf-8')
