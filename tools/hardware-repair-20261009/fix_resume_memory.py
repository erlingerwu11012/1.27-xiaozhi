from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'work/core/utils/tool_harness/memory_policy.py';s=p.read_text(encoding='utf-8');a=s.index('def memory_intent(query):');b=s.index('\ndef item_version',a)
s=s[:a]+'''def memory_intent(query):
    from core.utils.operation_control import content_text
    q=content_text(query).strip()
    # Quoted, hypothetical and explanatory mentions do not grant write authority.
    if re.search(r'[“”「」]|如果|假设|这句话|什么意思|是什么意思|怎么(?:改|删|忘)|为什么',q):return 'read'
    if re.search(r'音量|声音|亮度|屏幕|卡片|闹钟|拍照|相机|壁纸|渲染|习惯|便签|提醒',q):return 'read'
    if re.search(r'我(?:就|只是)?.{0,3}问|上下文|看不着|看不到|(?:没|没有|并没有).{0,8}(?:让|要求)|(?:别|不要|不用|不许|不能).{0,8}(?:修改|更正|纠正|删除|乱改|更新)|你(?:在|又|刚才)?(?:更正|修改|纠正).{0,8}(?:什么|啥)',q):return 'read'
    # The question word can belong to the selected fact, e.g. '叫什么那条记忆'.
    # Require a current directive, not a description that the speaker forgot something.
    if re.search(r'忘掉|遗忘|别记着|不要记着|(?:请|帮我|替我|你把|你将).{0,60}忘(?:了|记|掉)?|(?:记忆|记录|那件事).{0,10}(?:删|忘)|(?:删掉|删除|忘记).{0,30}(?:记忆|记录|那件事)',q):return 'forget'
    if re.search(r'忘记了|忘了',q):return 'read'
    if re.search(r'你(?:是不是|是否|刚才|已经).{0,12}(?:改|更正|更新)|(?:更正|修改|纠正).{0,4}(?:什么|啥)',q):return 'read'
    if re.search(r'改一下|改成|改为|更正|纠正|(?:更新|修改).{0,12}(?:记忆|偏好|记录)|(?:记忆|偏好|记录).{0,12}(?:更新|修改|改一下)|(?:把|将).{0,60}(?:更新|修改)',q):return 'correct'
    return 'read'
''' +s[b:];p.write_text(s,encoding='utf-8')
p=R/'work/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8').replace("r'记忆|偏好|饮料|爱喝|爱吃'","r'记忆|偏好|饮料|饮品|爱喝|爱吃|喝(?:什么|啥|哪)|吃(?:什么|啥|哪)'");p.write_text(s,encoding='utf-8')
p=R/'work/core/utils/tool_harness/reply_composer.py';s=p.read_text(encoding='utf-8');s=s.replace('只描述本次确认的动作和数值。','只描述本次确认的动作和数值。\n本轮只有查询时，应明确没有修改，不能迎合用户质疑而承认不存在的误操作。不编造自己的动机或承诺自动记住新内容。不要连续重复道歉。')
needle="    writes=[r for r in results"
a=s.index(needle)
insert='''    if any(r.tool=='memory_search' for r in results):
        for clause in re.split('[，,。；;]',text):
            if re.search(r'没有|并未|尚未|不能|不会|未曾|不再|无法|没(?:有)?(?:改|删|忘)|只是|不需要',clause):continue
            if re.search(r'(?:删除|删掉|忘掉|更正|修改|更新|改好|改过来).{0,12}(?:了|啦|完成|成功)|(?:已经|已|帮你|替你).{0,30}(?:删除|删掉|忘掉|更正|修改|更新)',clause):
                target='memory_forget' if re.search(r'删除|删掉|忘掉',clause) else 'memory_correct'
                if not any(r.tool==target and r.state=='completed' for r in results):return True
'''
s=s[:a]+insert+s[a:];p.write_text(s,encoding='utf-8')
p=R/'java/RecentArchiveService.java';s=p.read_text(encoding='utf-8');needle='        Set<String> result=new LinkedHashSet<>();';s=s.replace(needle,needle+'\n        if(query.matches("(?s).*(爱喝|喝什么|喝啥|喝哪|饮料|饮品|喜欢喝).*"))result.addAll(List.of("喝","咖啡","茶","牛奶","果汁","可乐","饮料"));',1);p.write_text(s,encoding='utf-8')
