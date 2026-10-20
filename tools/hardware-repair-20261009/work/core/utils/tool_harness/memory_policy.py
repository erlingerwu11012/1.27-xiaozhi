"""Current-turn memory authority and normalized facts. No model-supplied identity."""
import hashlib,json,re

def normalize_fact(value):
    if not isinstance(value,str):return ''
    text=value.strip()
    for _ in range(3):
        if not text.startswith('{'):break
        try:row=json.loads(text)
        except (ValueError,TypeError):return ''
        if not isinstance(row,dict) or not isinstance(row.get('content'),str):return ''
        if row.get('role') not in (None,'user'):return ''
        text=row['content'].strip()
    if not text or re.search(r'[{}]|\[来源[:：]|verified_results|tool_calls|catalog_version',text):return ''
    if re.search(r'[？?]|(?:我|你).{0,15}(?:喜欢|爱喝|喝过|爱吃).{0,8}(?:什么|啥)|(?:你还|还)?记得.{0,8}(?:吗|么)|怎么|为什么|能不能|是不是',text):return ''
    return text

def memory_intent(query):
    from core.utils.operation_control import content_text
    q=content_text(query).strip()
    # Quoted, hypothetical and explanatory mentions do not grant write authority.
    if re.search(r'[“”「」]|如果|假设|这句话|什么意思|是什么意思|怎么(?:改|删|忘)|为什么',q):return 'read'
    if re.search(r'音量|声音|亮度|屏幕|卡片|闹钟|拍照|相机|壁纸|渲染|习惯|便签|提醒',q):return 'read'
    if re.search(r'我(?:就|只是)?.{0,3}问|上下文|看不着|看不到|(?:没|没有|并没有).{0,8}(?:让|要求)|(?:别|不要|不用|不许|不能).{0,8}(?:修改|更正|纠正|删除|乱改|更新)|你(?:在|又|刚才)?(?:更正|修改|纠正).{0,8}(?:什么|啥)',q):return 'read'
    if re.search(r'是不是|是否|(?:删|改|忘|更新|更正).{0,5}(?:过|了吗|了没|吗[？?]?$)',q) and not re.search(r'请|帮我|替我|能不能帮|把|将',q):return 'read'
    # The question word can belong to the selected fact, e.g. '叫什么那条记忆'.
    # Require a current directive, not a description that the speaker forgot something.
    if re.search(r'忘掉|遗忘|别记着|不要记着|(?:请|帮我|替我|你把|你将).{0,60}忘(?:了|记|掉)?|(?:记忆|记录|那件事).{0,10}(?:删|忘)|(?:删掉|删除|忘记).{0,30}(?:记忆|记录|那件事)',q):return 'forget'
    if re.search(r'忘记了|忘了',q):return 'read'
    if re.search(r'你(?:是不是|是否|刚才|已经).{0,12}(?:改|更正|更新)|(?:更正|修改|纠正).{0,4}(?:什么|啥)',q):return 'read'
    if re.search(r'改一下|改成|改为|更正|纠正|(?:更新|修改).{0,12}(?:记忆|偏好|记录)|(?:记忆|偏好|记录).{0,12}(?:更新|修改|改一下)|(?:把|将).{0,60}(?:更新|修改)',q):return 'correct'
    return 'read'

def item_version(text):return hashlib.sha256(text.encode()).hexdigest()
