"""Bind a semantic decision to this request, independently of tool receipts."""
import re
from core.utils.operation_control import content_text


def explicitly_clear_all(text):
    q=content_text(text)
    # Deictic collections (these/all these) never mean the entire personal store.
    return bool(re.search(r'(?:清空|删除|删掉|忘掉|遗忘).{0,12}(?:全部|所有|整个)(?:的)?(?:个人)?记忆(?:库)?|(?:全部|所有)(?:的)?(?:个人)?记忆.{0,8}(?:清空|删除|删掉|忘掉)',q)) and not re.search(r'这些|这几条|刚才|饮品|饮料|偏好',q)


def validate_authority(decision,tool,query,original_query,conn):
    if decision.intent!='action' or tool not in decision.authorized_writes:
        raise ValueError('write_requires_current_action_authorization: explicit intent=action and authorized_writes must contain '+tool+'; quote current user words in intent_evidence')
    evidence=decision.intent_evidence.strip()
    q=content_text(query)
    # supplement() inserts this server-owned delimiter between verbatim user
    # turns. It is not part of the authorization quote and carries no intent.
    citation_source=q.replace('[该任务已收到的补充，最新明确改口优先]','')
    if not evidence or re.sub(r'\s+','',evidence) not in re.sub(r'\s+','',citation_source):
        raise ValueError('write_authorization_evidence_not_in_user_request')
    # Defense against a query being labelled as an action. This guard only
    # denies an unambiguous interrogative span; it never dispatches an action.
    if re.search(r'(?:了吗|了没|过吗|响了吗|有没有|是否|是不是|存了吗|存进.{0,5}了吗)[？?。！! ]*$',evidence) and not re.search(r'请.{0,12}(?:设置|停止|删除|保存)|帮我.{0,12}(?:设置|停止|删除|保存)',evidence):
        raise ValueError('query_does_not_authorize_write')
    if re.match(r'^(?:如果|假设|举例|引用|我只是问)',evidence):
        raise ValueError('quoted_or_hypothetical_action_not_authorized')
    if tool in {'reminder_action','alarm_dismiss'}:
        from core.utils.device_speech_origin import matches_device_speech
        if matches_device_speech(conn,content_text(original_query)):
            raise ValueError('device_speech_is_not_user_authorization')
    if tool=='reminder_action' and not re.search(r'完成|做完|办完|好了|拿到|拿了|收到了|吃完|喝完|跳过|稍后|延后|推迟|静音|别响|不用提醒|主动作|主按钮',evidence):
        raise ValueError('card_action_requires_explicit_user_intent')


def normalize_character_spelling(tool,args,query):
    """Apply only explicit, known character explanations to a named span."""
    if tool not in {'memory_add','memory_correct'}:return args
    key='fact' if tool=='memory_add' else 'replacement'
    value=args.get(key,'');named=re.search(r'(?:叫|姓名是|名字是)([^，,。；;\s]{1,20})',value)
    if not named:return args
    name=named[1]
    for phrase,char,homophones in [('弓长张','张','章张'),('花蕊的蕊','蕊','锐瑞蕊'),('秦朝的秦','秦','琴勤秦')]:
        if phrase not in content_text(query) or char in name:continue
        indexes=[i for i,c in enumerate(name) if c in homophones]
        if len(indexes)!=1:continue  # ambiguous names still require clarification
        i=indexes[0];name=name[:i]+char+name[i+1:]
    value=value[:named.start(1)]+name+value[named.end(1):]
    value=re.sub(r'[，,]\s*(?:弓长张|花蕊的蕊|秦朝的秦)(?=[，,。]|$)','',value)
    return {**args,key:value.rstrip('，,。 ')}


def validate_memory_write(tool,args,query):
    from .memory_policy import normalize_fact
    if args.get('match')=='*' and not explicitly_clear_all(query):
        raise ValueError('memory_clear_all_requires_explicit_store_scope_select_record_ids')
    if tool=='memory_add':
        fact=args.get('fact','')
        if not fact or normalize_fact(fact)!=fact.strip():raise ValueError('memory_fact_must_exclude_instructions')
    if tool=='memory_correct':
        replacement=args.get('replacement','')
        if not replacement or normalize_fact(replacement)!=replacement.strip():raise ValueError('memory_replacement_must_be_complete_fact')
        old=args.get('match','')
        # A bare new name cannot replace a fact with a relationship. The model
        # must construct the whole updated fact; never synthesize a relation here.
        relations=('老婆','妻子','配偶','丈夫','老公','妈妈','母亲','爸爸','父亲','女儿','儿子','朋友','同事')
        if any(x in old for x in relations) and not any(x in replacement for x in relations):
            raise ValueError('memory_replacement_loses_relationship')
    if tool in {'memory_add','memory_correct'}:
        value=args.get('fact' if tool=='memory_add' else 'replacement','')
        named=re.search(r'(?:叫|姓名是|名字是)([^，,。；;\s]{1,20})',value)
        spelling=named[1] if named else re.split('[，,。；;]',value)[0]
        # Explicit character explanations outrank the ASR's earlier homophone.
        # Never guess an unfamiliar character: request clarification instead.
        for phrase,char in [('弓长张','张'),('花蕊的蕊','蕊'),('秦朝的秦','秦')]:
            if phrase in content_text(query) and char not in spelling:
                raise ValueError('memory_name_conflicts_with_explicit_character_clarify')
