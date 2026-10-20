from pathlib import Path
R=Path(__file__).parent
p=R/'candidate/core/utils/tool_harness/presentation.py';s=p.read_text(encoding='utf-8-sig');s+='''

def structured_read_reply(name,body):
    if name=='self_camera_identify_person':
        status=body.get('status')
        if status=='known':
            display=body.get('display_name') or body.get('name')
            return ('识别到的是'+display+'。') if isinstance(display,str) and display else '已匹配到登记人员，但未返回姓名。'
        return {'unknown':'看到人脸了，但没有确认是谁。','ambiguous':'识别结果有歧义，这次没有确认身份。','no_face':'这次没有检测到人脸。','empty':'还没有可用于识别的人脸资料。'}.get(status,'这次没有确认身份。')
    if name=='self_get_system_info':
        parts=[]
        if isinstance(body.get('chip'),str):parts.append('芯片是'+body['chip'])
        if type(body.get('flash_size')) is int:parts.append('Flash容量为'+str(round(body['flash_size']/1048576,2))+'MB')
        if type(body.get('free_heap')) is int:parts.append('剩余内存为'+str(body['free_heap'])+'字节')
        return '，'.join(parts)+'。' if parts else None
    if name=='self_screen_get_render_status':
        parts=[]
        for key,label in [('mode','渲染模式'),('running_mode','当前渲染模式'),('profile','配置'),('running_profile','当前配置')]:
            value=body.get(key)
            if isinstance(value,str) and value:parts.append(label+'是'+value)
        return '，'.join(parts)+'。' if parts else None
    return None
''';p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/tool_harness/contracts.py';s=p.read_text(encoding='utf-8-sig');s=s.replace("            reply=json.dumps(body,ensure_ascii=False) if not isinstance(body,str) else body", "            if isinstance(body,dict) and name in {'self_get_system_info','self_screen_get_render_status','self_camera_identify_person'}:\n                from .presentation import structured_read_reply\n                reply=structured_read_reply(name,body)\n                if not reply:return out('unknown','查询返回的业务信息不完整。','missing_user_facts')\n            else:reply=json.dumps(body,ensure_ascii=False) if not isinstance(body,str) else body")
s=s.replace('elif name==\'camera_face_enroll_status\':reply=f"人脸采集状态是{body[\'state\']}，已采集{body[\'accepted_count\']}张。"', 'elif name==\'camera_face_enroll_status\':reply=f"人脸采集{dict(capturing=\'正在进行\',idle=\'尚未开始\',completed=\'已完成\',failed=\'失败\',cancelled=\'已取消\').get(body[\'state\'],\'状态待确认\')}，已采集{body[\'accepted_count\']}张。"')
p.write_text(s,encoding='utf-8')
