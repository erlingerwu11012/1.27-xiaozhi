$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
Set-Location 'E:\github\github_code\all\4.30'
$env:Path = 'E:\Espressif\python_env\idf5.5_py3.11_env\Scripts;' + $env:Path
. 'E:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1'
& python 'E:\Espressif\frameworks\esp-idf-v5.5.4\tools\idf.py' -B build-experience-repair-20261009 build *> tools\hardware-repair-20261009\firmware-build.log
$LASTEXITCODE | Set-Content tools\hardware-repair-20261009\firmware-build.exit

