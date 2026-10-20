from pathlib import Path
import shutil,tarfile
stage=Path(__file__).parent;host=stage/'host'
for name in ['habit_manager.cc','habit_manager.h','note_manager.cc','note_manager.h','person_turn.h','weekly_schedule.h','person_directory.cc','person_directory.h']:
 shutil.copy2(Path('main')/name,host/name)
for name in ['cJSON.c','cJSON.h']:shutil.copy2(Path('E:/Espressif/frameworks/esp-idf-v5.5.4/components/json/cJSON')/name,host/name)
with tarfile.open(stage/'host-tests.tgz','w:gz') as tar:tar.add(host,arcname='host')
