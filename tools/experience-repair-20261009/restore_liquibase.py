from pathlib import Path
p=Path(__file__).parent/'start_api.py';s=p.read_text(encoding='utf-8-sig').replace(",'--spring.liquibase.enabled=false'",'');p.write_text(s,encoding='utf-8')
