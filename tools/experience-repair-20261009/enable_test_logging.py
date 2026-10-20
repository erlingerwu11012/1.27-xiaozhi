from pathlib import Path
p=Path(__file__).parent/'start_api.py';s=p.read_text(encoding='utf-8-sig').replace('--spring.profiles.active=experience-test','--spring.profiles.active=test,experience-test');p.write_text(s,encoding='utf-8')
