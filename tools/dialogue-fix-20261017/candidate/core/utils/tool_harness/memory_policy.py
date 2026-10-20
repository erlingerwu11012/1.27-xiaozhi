"""Current request authority. Negation never vetoes a different clause's request."""
import hashlib,json,re

def normalize_fact(value):
    if not isinstance(value,str):return ''
    text=value.strip()
    for _ in range(3):
        if not text.startswith('{'):break
        try:row=json.loads(text)
        except (ValueError,TypeError):return ''
        if not isinstance(row,dict) or not isinstance(row.get('content'),str) or row.get('role') not in (None,'user'):return ''
        text=row['content'].strip()
    text=re.sub(r'^(?:(?:那|好|嗯|呃)[，, ]*)?(?:(?:请|你|帮我|给我|替我|现在|这次)\s*)*(?:记一下|记住|保存(?:一下)?|记录(?:一下)?)[，,：: ]*','',text).strip()
    text=re.sub(r'[，,。 ]*(?:请|你|帮我|给我)?(?:存到记忆库(?:里)?|存进去|保存到记忆库)(?:吧|啊|呀)?[。！! ]*$','',text).strip()
    if re.fullmatch(r'(?:那|好|嗯|呃|请|你|帮我|给我|替我|把|将|这条|这些|这个|全部|所有|刚才|记忆|记忆库|记录|了|吧|啊|呀|，|,|。|！|!|\s)*(?:保存|存|删|删除|删掉|忘掉|更正|修改|待机|不用了|算了|取消|记一下|记好|记住).{0,15}',text):return ''
    if re.search(r'(?:删除|删掉|忘掉|更正|修改).{0,12}(?:记忆|记录)|(?:记忆|记录).{0,12}(?:删除|删掉|忘掉)|^(?:行[，, ]*)?(?:待机吧|不聊了|再见|不用了|取消吧)[。！! ]*$',text):return ''
    if not text or re.search(r'[{}]|\[来源[:：]|verified_results|tool_calls|catalog_version',text):return ''
    if re.search(r'[？?]|(?:我|你).{0,15}(?:喜欢|爱喝|爱吃).{0,8}(?:什么|啥)|怎么|为什么|能不能|是不是',text):return ''
    return text

def memory_intent(query):
    from core.utils.operation_control import content_text
    q=content_text(query).strip()
    if re.match(r'^(?:假设|如果我说|这句话|我(?:就|只是)?.{0,3}问)',q):return 'read'
    if re.search(r'(?:不是|没|没有)(?:让|叫|要求)你.*[吗？?]|你(?:是不是|是否|刚才|已经).{0,12}(?:改|删|更正|更新)|(?:删|改|忘).{0,5}(?:了吗|了没|过吗)',q) and not re.search(r'[，,。](?:现在|这次)?(?:请|你)?(?:帮我|替我|把|给我)',q):return 'read'
    for clause in reversed(re.split(r'[，,；;。\n]|但是|不过|而是',q)):
        c=clause.strip()
        if re.match(r'^(?:先)?(?:别|不要|不用|不许|不能|不是|没让|没有要求|我只是)',c):continue
        if re.search(r'^(?:请|你|帮我|替我|给我|现在|这次)*(?:记一下|记住|记着)(?!了|的|吗|什么|啥)|^(?:请|你|帮我|替我|给我|现在|这次)*(?:保存(?:一下)?|存一下)(?:[：:]|$)|(?:把|将).{0,30}(?:记住|保存到记忆)|保存.{0,12}(?:事实|记忆)',c):return 'add'
        if re.search(r'忘掉|遗忘|(?:请|帮我|替我|你把|你将|把|将).{0,60}忘(?:了|记|掉)?|(?:记忆|记录|资料|事实|那件事).{0,10}(?:删|忘)|(?:删掉|删除|忘记).{0,30}(?:记忆|记录|资料|事实|那件事)',c):return 'forget'
        if re.search(r'改一下|改成|改为|更正|纠正|(?:更新|修改).{0,12}(?:记忆|偏好|记录)|(?:记忆|偏好|记录).{0,12}(?:更新|修改)|(?:把|将).{0,60}(?:更新|修改)',c) and not re.search(r'音量|声音|亮度|屏幕|闹钟|相机|壁纸|渲染|便签|卡片',c):return 'correct'
    if re.search(r'别记着|不要记着|别再记住',q):return 'forget'
    return 'read'

def item_version(text):return hashlib.sha256(text.encode()).hexdigest()
