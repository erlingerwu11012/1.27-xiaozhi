from pathlib import Path
p=Path('tools/experience-repair-20261009/run_vision_http.py');s=p.read_text(encoding='utf-8-sig').replace('from PIL import Image','import base64')
s=s.replace(" image=io.BytesIO();Image.new('RGB',(64,64),(0,0,255)).save(image,format='JPEG');picture=image.getvalue();headers=", " picture=base64.b64decode((stage/'synthetic-blue-jpeg.b64').read_text());headers=")
p.write_text(s,encoding='utf-8')
from PIL import Image
import io,base64
image=io.BytesIO();Image.new('RGB',(64,64),(0,0,255)).save(image,format='JPEG')
Path('tools/experience-repair-20261009/synthetic-blue-jpeg.b64').write_text(base64.b64encode(image.getvalue()).decode(),encoding='utf-8')
