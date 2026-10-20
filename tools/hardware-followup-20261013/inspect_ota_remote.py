from pathlib import Path
s=Path('/root/prjs/tmp/hardware-followup-20261013/manager-api/src/main/java/xiaozhi/modules/rolepack')
for pattern in ['*Device*Controller.java','RoleDeployStateMachine.java','RolePackConstants.java']:
 for p in s.rglob(pattern):print(str(p.relative_to(s)));print(p.read_text())
