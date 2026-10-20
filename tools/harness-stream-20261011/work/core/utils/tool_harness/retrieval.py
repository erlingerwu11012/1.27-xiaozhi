"""Session-scoped recall. Scores select descriptions, never authorize actions."""
import re
from .contracts import PREREQUISITES


def recall(query, tools, policy, task=None, previous=None, required=(), expanded=()):
    from core.providers.tools.tool_catalog import ToolCatalogBuilder
    from core.providers.tools.tool_selector import ToolSelector
    catalog = ToolCatalogBuilder().build([d.description for d in tools.values()], tools)
    result = ToolSelector(policy=policy).select(query, catalog, turn_id='harness', mode='enabled')
    names = list(sorted(set(required) & set(tools)))
    if task:
        names.extend(task.write_tools)
    # Recall a verified target for object-free follow-ups; the model still decides
    # whether that target is appropriate and must clarify actual ambiguity.
    if not re.search(r'音量|声音|屏幕|亮度',query) and re.search(r'再.{0,5}(?:亮|暗|大|小)|最低|最高|压到|调到|删掉|这个|那个',query):
        if previous:
            names.extend(r.tool for r in previous.results if r.state == 'completed'
                         and r.tool in {'self_audio_speaker_set_volume', 'self_screen_set_brightness'})
    for score in result.candidate_scores:
        if any(reason.startswith(('scene:', 'phrase:', 'state:', 'followup_of:'))
               or reason == 'substr_query' for reason in score.reasons):
            names.append(score.public_name)
    chosen = list(dict.fromkeys(n for n in names if n in tools))[:8]
    selected = []
    for name in list(dict.fromkeys(list(expanded)+chosen)):
        needs = list(PREREQUISITES.get(name, ()))
        if name in {'self_audio_speaker_set_volume', 'self_screen_set_brightness'}:
            needs.append('self_get_device_status')
        bundle = [n for n in [name] + needs if n in tools and n not in selected]
        if len(selected) + len(bundle) <= 16:
            selected.extend(bundle)
    return selected[:16]


def retrieve(query, tools, policy):
    # Capability descriptions can be broader than the original user's words.
    selected=recall(query, tools, policy)
    if selected:return selected
    # Character bigrams also recall capability descriptions without a vector service.
    words=set(re.findall(r'[a-z_]{3,}|[\u4e00-\u9fff]{2}',query.lower()))
    ranked=[]
    for name,definition in sorted(tools.items()):
        text=name+' '+definition.description['function'].get('description','').lower()
        score=sum(len(word) for word in words if word in text)
        if score:ranked.append((-score,name))
    names=[name for _,name in sorted(ranked)[:8]]
    return recall('',tools,policy,required=names)


def availability(query,manager,tools,selected):
    from .registry import manifest
    available=sorted(set(selected)&set(tools))
    unavailable=[{'name':r['name'],'reason':r['availability']} for r in manifest(manager)
                 if r['availability']!='available' and (r['name'] in query or any(word in r['purpose'] for word in re.findall(r'[\u4e00-\u9fff]{2}',query)))]
    actor=getattr(getattr(manager,'conn',None),'person_turn',None)
    personal={'memory_search','memory_add','memory_correct','memory_forget','alarm_list','note_list','habit_list','habit_learn','habit_delete','habit_confirm','habit_reject'}
    if not actor or not actor.eligible:
        denied=set(available)&personal
        unavailable.extend({'name':name,'reason':'permission_denied_identity_unconfirmed'} for name in sorted(denied))
        available=[name for name in available if name not in denied]
    reasons={row['reason'] for row in unavailable}
    status='available' if available else 'permission_denied' if any('permission_denied' in reason for reason in reasons) else 'device_not_supported' if 'device_not_supported' in reasons else 'temporarily_unavailable' if 'not_connected' in reasons else 'not_integrated'
    return {'available':available,'unavailable':unavailable,
            'status':status,
            'instruction':'仅列出实际可用Schema；权限仍由原身份与执行器校验。未命中不证明没有需求，不得编造替代操作。'}
