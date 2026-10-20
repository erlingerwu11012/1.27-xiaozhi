from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'work/core/utils/tool_harness/reply_composer.py';s=p.read_text(encoding='utf-8');needle="    for r in results:\n        if r.tool=='self_screen_set_brightness'"
a=s.index(needle);s=s[:a]+'''    from core.utils.remind_time import cn_num_to_int
    numbers=r'[零〇一二两三四五六七八九十百\\d]+'
    for r in results:
        if r.state!='completed' or not isinstance(r.payload,dict):continue
        if r.tool=='self_screen_set_brightness':
            expected=r.payload.get('brightness_level',r.payload.get('brightness'))
            values=re.findall(r'(?:亮度|屏幕)[^，,。；;]{0,15}?第?('+numbers+r')\\s*档',text)
        elif r.tool=='self_audio_speaker_set_volume':
            expected=r.payload.get('volume')
            values=re.findall(r'(?:音量|声音)[^，,。；;]{0,20}?(?:调到|调至|设置为|设为|设成|是|为|到|成)\\s*('+numbers+r')\\s*(?:%|％|了|[。！？!?,， ]|$)',text)
        else:continue
        if expected is not None and any(cn_num_to_int(v)!=expected for v in values):return True
''' +s[a:];p.write_text(s,encoding='utf-8')
p=R/'test_resume_speech.py';s=p.read_text(encoding='utf-8').replace("('亮度已调到五档。',False)","('亮度已调到五档。',True),('亮度设为第四档。',False)");p.write_text(s,encoding='utf-8')
