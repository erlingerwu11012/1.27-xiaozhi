from pathlib import Path
import re
p=Path('/root/prjs/tmp/hardware-followup-20261013/private-gateway-diagnostic.log')
for line in p.read_text().splitlines():
 if re.search('timed out|timeout|error is|deadline|401|503',line,re.I):
  line=re.sub(r'(sk-|Bearer\s+)[A-Za-z0-9_.:-]+',r'\1[REDACTED]',line)
  line=re.sub(r'(token|key|authorization|secret)([" =:]+)[^\s,}"]+',r'\1\2[REDACTED]',line,flags=re.I)
  print(line[:450])
