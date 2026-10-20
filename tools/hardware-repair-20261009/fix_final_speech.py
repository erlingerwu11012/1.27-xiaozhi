from pathlib import Path
R=Path('tools/hardware-repair-20261009')
p=R/'work/core/utils/tool_harness/reply_composer.py';s=p.read_text(encoding='utf-8');s=s.replace('不要连续重复道歉。','不要连续重复道歉。\n亮度回执若含brightness_level，回复实际档位，不把输入的百分比当作实际百分比；duty_percent仅是硬件PWM占空比，不将其当作用户界面百分比。\n识人未确认时，只说明尚未认出；回执未给出原因时，不猜光线、角度、距离或网络原因。')
a=s.index("    for r in results:\n        if r.tool in {'self_audio_speaker_set_volume','self_screen_set_brightness'}")
s=s[:a]+'''    for r in results:
        if r.tool=='self_screen_set_brightness' and r.state=='completed' and isinstance(r.payload,dict) and type(r.payload.get('brightness_level')) is int:
            # A compatibility percentage is an input, not the physical/display output.
            # Speak the verified discrete level instead of inventing a percentage scale.
            if re.search(r'\\d+(?:\\.\\d+)?\\s*[%％]|百分之[零〇一二两三四五六七八九十百\\d]+|[一二两三四五六七八九十]成',text):return True
''' +s[a:];p.write_text(s,encoding='utf-8')
p=R/'work/core/utils/tool_harness/presentation.py';s=p.read_text(encoding='utf-8');a=s.index("    if re.search(r'\\b(?:self_");b=s.index('    sentences=',a);s=s[:a]+'''    # Explaining a hypothetical workflow is not a failed operation. Translate
    # known internal capability names rather than replacing the answer with failure.
    from .contracts import LABELS
    for name,label in sorted(LABELS.items(),key=lambda x:len(x[0]),reverse=True):
        text=re.sub(r'(?<![a-zA-Z0-9_])'+re.escape(name)+r'(?![a-zA-Z0-9_])',label,text)
    text=re.sub(r'\\bself_[a-z_]+\\b','设备功能',text)
''' +s[b:];p.write_text(s,encoding='utf-8')
p=R/'work/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');s=s.replace('chat根据对话中已有事实回答，不能因无法访问外部文件而否认用户已提供的进度；','chat根据对话中已有事实回答，复述时保持时间、动作、完成量和否定范围，不把早先写完的正文说成仅修改标题，不把昨天的动作挪到上周。不要为了接话改写用户事实；不能因无法访问外部文件而否认用户已提供的进度；');s=s.replace('每步字段 id、tool、arguments、depends_on，','普通聊天与假设说明使用日常用语，不展示内部工具名称、字段名或调用代码。\n每步字段 id、tool、arguments、depends_on，',1);p.write_text(s,encoding='utf-8')
p=R/'run_model.py';s=p.read_text(encoding='utf-8');s=s.replace("r'这次请求没有执行完|确认操作目标或参数|尚未确认任何新的修改'","r'这次请求没有执行完|这次操作没有完成|确认操作目标或参数|尚未确认任何新的修改'")
s=s.replace(" if speech.startswith(('{','['))", " from core.utils.tool_harness.reply_composer import unsafe\n from core.utils.tool_harness.models import StepResult\n if results and unsafe(speech,[StepResult.model_validate(x) for x in results]):errors.append('unverified_spoken_claim')\n if '上周写好一半' in row['query'] and '昨天只改了标题' in row['query'] and re.search(r'上周.{0,15}(?:停留|主要|只是|只).{0,10}标题',speech):errors.append('progress_time_action_swapped')\n if speech.startswith(('{','['))")
p.write_text(s,encoding='utf-8')
