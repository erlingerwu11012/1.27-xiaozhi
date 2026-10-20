from pathlib import Path
S=Path('tools/hardware-repair-20261009');W=S/'work'
p=Path('main/mcp_tools/mcp_tools_camera.cc');s=p.read_text().replace('"vision_not_ready:" + VisionCredentialStore','"vision_" + VisionCredentialStore');p.write_text(s)
p=W/'core/utils/tool_result.py';s=p.read_text().replace("    'vision_not_ready':", "    'vision_awaiting_hello':'视觉连接还在建立，这次没有拍照。',\n    'vision_awaiting_initialize':'视觉配置尚未送达设备，这次没有拍照。',\n    'vision_expired':'视觉授权已过期，这次没有拍照。',\n    'vision_missing_identity_url':'识人服务地址尚未配置，这次没有识人。',\n    'vision_incomplete_pending':'视觉配置不完整，这次没有拍照。',\n    'vision_connection_closed':'视觉连接已经断开，这次没有拍照。',\n    'vision_vision_session_mismatch':'视觉授权属于其他会话，这次没有拍照。',\n    'capture_or_upload_failed':'拍照或上传失败，这次没有获得识别结果。',\n    'vision_not_ready':")
s=s.replace('这次没有确认说话人的身份，请本人再说一次，或在屏幕上操作。','这次没听出是谁，请本人再说一句让我确认。');p.write_text(s)
p=W/'core/utils/tool_harness/runtime.py';s=p.read_text().replace("    if not re.search(r'查|看|确认|多少|多大|几档',positive):return None", "    if re.search(r'(?:这是|现在是|是不是|是否).{0,5}(?:最高档|最低档|最亮|最暗)|(?:最高档|最低档).{0,3}(?:了吗|吗|么)',positive):return 'self_get_device_status'\n    if not re.search(r'查|看|确认|多少|多大|几档',positive):return None")
s=s.replace("                        if pre in {'alarm_list','note_list','habit_list'} and isinstance(pre_result.payload,str):", "                        if pre=='alarm_list' and isinstance(pre_result.payload,dict):\n                            if arguments.get('index') not in set(range(1,len(pre_result.payload.get('items',[]))+1)):raise ValueError('object_not_in_current_list')\n                        if pre in {'alarm_list','note_list','habit_list'} and isinstance(pre_result.payload,str):")
p.write_text(s)
print('error causes and structured alarm validation ready')
