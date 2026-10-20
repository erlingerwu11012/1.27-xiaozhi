from pathlib import Path
R=Path(__file__).parent;p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
old="        ratio=re.search(r'(?:到|为|用|改成|设成|换成)"
new="""        level=re.search(r'(?:到|成|为|至|设在)\\s*第?([零〇一二两三四五六七八九十百\\d]+)档',clause)
        if level and re.search('屏幕|亮度',clause):
            from core.utils.remind_time import cn_num_to_int
            number=cn_num_to_int(level[1])
            if number is not None:expected['self_screen_set_brightness']={'brightness':number}
        ratio=re.search(r'(?:到|为|用|改成|设成|换成)"""
assert old in s;s=s.replace(old,new)
old="    return result\n\nclass Harness:"
new="""    # A trailing quantity can qualify the preceding explicit adjustment clause.
    # This is an additional consistency check, never a tool admission requirement.
    if not re.search(r'解释|介绍|意思|为什么|如何|怎么',full):
        match=re.search(r'(声音|音量|屏幕|亮度).{0,6}?(提|加|升|增|减|降)(?:一)?(?:小)?(?:格|档|点)',full)
        if match:
            quantity=re.search(r'([零〇一二两三四五六七八九十百\\d]+)(?:个)?点',full)
            delta=cn_num_to_int(quantity[1]) if quantity else 10
            if delta:
                name='self_screen_set_brightness' if match[1] in {'屏幕','亮度'} else 'self_audio_speaker_set_volume'
                result[name]=delta if match[2] in {'提','加','升','增'} else -delta
    return result

class Harness:"""
assert old in s;s=s.replace(old,new)
old="                if re.search(noun,clause) and re.search(r'调(?:到|成|高|低|亮|暗|至)|设(?:为|成|到|置)|改(?:为|成|到)|提高|降低|最大|最小|最高|最低|最亮|最暗',clause):targets.add(name)"
new="""                display_config=name=='self_screen_set_brightness' and re.search(r'渲染|render|spine|lvgl|像素',clause,re.I) and '亮度' not in clause
                if not display_config and re.search(noun,clause) and re.search(r'调(?:到|成|高|低|亮|暗|至)|设(?:为|成|到|置)|改(?:为|成|到)|提高|降低|最大|最小|最高|最低|最亮|最暗',clause):targets.add(name)"""
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
