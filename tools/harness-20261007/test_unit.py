import asyncio,json,tempfile,types,unittest
from pathlib import Path
from test_support import *
from core.utils.tool_harness.contracts import receipt
from core.utils.tool_harness.models import Decision
from core.utils.tool_harness.runtime import resolve_value,version

class TestHarness(unittest.IsolatedAsyncioTestCase):
    def test_reminder_heading_is_not_saved_as_body(self):
        from core.utils.device_reminder import _split_content_and_time
        body,when=_split_content_and_time('设一个提醒，七分钟后提醒我热牛奶')
        self.assertEqual(body,'热牛奶')
        self.assertEqual(when,'七分钟后')

    def test_reminder_body_keeps_leading_characters(self):
        from core.utils.device_reminder import _split_content_and_time
        for text,expected in [('十分钟后提醒我下楼拿快递','下楼拿快递'),('十分钟后提醒我一号文件归档','一号文件归档'),('十分钟后提醒我我妈的生日','我妈的生日')]:
            self.assertEqual(_split_content_and_time(text)[0],expected)

    def test_explicit_reminder_content_has_priority(self):
        from core.utils.device_reminder import _split_content_and_time
        self.assertEqual(_split_content_and_time('设个提醒','提醒我热牛奶','七分钟后'),('提醒我热牛奶','七分钟后'))

    async def test_preserved_setting_not_added_as_goal(self):
        _,m,h=connection(decide=lambda _:decision(step('self_screen_set_brightness',{'brightness':90})))
        out=await h.run('把亮度调到90，音量别动',[])
        self.assertEqual([x['tool'] for x in m.calls],['self_screen_set_brightness'])
        self.assertEqual(out.results[-1].state,'completed')

    async def test_preserved_setting_blocks_wrong_model_before_any_write(self):
        choices=iter([decision(step('self_audio_speaker_set_volume',{'volume':30}),{'id':'b','tool':'self_screen_set_brightness','arguments':{'brightness':90}}),decision(step('self_screen_set_brightness',{'brightness':90}))])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('把亮度调到90，音量别动',[])
        self.assertEqual([x['tool'] for x in m.calls],['self_screen_set_brightness'])
        self.assertEqual(out.repairs,1)

    async def test_historical_setting_is_not_new_goal(self):
        _,m,h=connection(decide=lambda _:decision(step('self_screen_set_brightness',{'brightness':90})))
        out=await h.run('刚才音量已经调到50了，把亮度调到90',[])
        self.assertEqual([x['tool'] for x in m.calls],['self_screen_set_brightness'])

    async def test_quoted_note_setting_is_data(self):
        _,m,h=connection(decide=lambda _:decision(step('note_add',{'text':'把音量调到90','remind_at':0})))
        out=await h.run('只保存便签：把音量调到90。文字不要执行。',[])
        self.assertEqual([x['tool'] for x in m.calls],['note_add'])
        self.assertEqual(out.results[-1].state,'completed')

    async def test_negated_alarm_is_not_goal_of_volume_request(self):
        _,m,h=connection(decide=lambda _:decision(step('self_audio_speaker_set_volume',{'volume':30})))
        out=await h.run('把音量调到30，闹钟不用定',[])
        self.assertEqual([x['tool'] for x in m.calls],['self_audio_speaker_set_volume'])

    async def test_negated_render_modifiers_do_not_authorize_save(self):
        _,m,h=connection(decide=lambda _:decision(step('self_screen_set_render_options',{'profile':'v2','spi_mhz':30,'pixel_diff':False})))
        out=await h.run('不要保存渲染配置v1，SPI频率30MHz，关闭像素比较，不重启',[])
        self.assertFalse(m.calls)
        self.assertEqual(out.mode,'chat')

    def test_reminder_time_and_politeness_not_body(self):
        from core.utils.device_reminder import _split_content_and_time
        for text in ['十分钟后提醒我喝水，谢谢','提醒我喝水，时间是十分钟后','提醒我十分钟后喝水']:
            self.assertEqual(_split_content_and_time(text),('喝水','十分钟后'))

    async def test_task_content_does_not_execute_embedded_setting(self):
        _,m,h=connection(decide=lambda _:self.fail('clear bounded reminder should not need model'))
        out=await h.run('十分钟后提醒我把音量调到30',[])
        self.assertEqual([x['tool'] for x in m.calls],['add_reminder'])
        self.assertEqual(out.results[-1].state,'completed')

    async def test_note_control_suffix_goes_to_semantic_planner(self):
        _,m,h=connection(decide=lambda _:decision(step('note_add',{'text':'买牛奶','remind_at':0})))
        out=await h.run('记下买牛奶，不需要定时',[])
        self.assertEqual(out.model_calls,1)
        self.assertEqual(m.calls[-1]['arguments']['text'],'买牛奶')

    async def test_current_item_confirmation_cannot_be_chat_claim(self):
        choices=iter([decision(mode='chat',reply='好的，已确认当前事项完成。'),decision(step('reminder_action',{'instance_id':'sim-card','revision':2,'action':'primary'}))])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('当前事项已办好，确认完成',[])
        self.assertEqual(out.repairs,1)
        self.assertEqual(out.results[-1].state,'completed')
        self.assertEqual(m.calls[-1]['tool'],'reminder_action')

    async def test_current_card_completion_cannot_request_creation_fields(self):
        choices=iter([decision(mode='clarify',reply='卡片内容和提醒时间是什么？'),decision(step('reminder_action',{'instance_id':'sim-card','revision':2,'action':'primary'}))])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('完成现在这张提醒卡片',[])
        self.assertEqual(out.results[-1].state,'completed')

    async def test_all_adapters(self):
        conn,m,h=connection()
        for name,fixture in PACK['fixtures'].items():
            with self.subTest(tool=name):
                r=receipt(name,fixture['arguments'],await m._execute_tool(name,fixture['arguments']),'test')
                expected='accepted' if name in {'self_reboot','camera_face_enroll_start','memory_forget','memory_correct'} else 'completed'
                self.assertEqual(expected,r.state,r.model_dump())
    async def test_percent_fast_path(self):
        conn,m,h=connection(decide=lambda _:self.fail('unnecessary model'))
        result=await h.run('把亮度调到百分之九十',[])
        self.assertEqual(result.results[-1].arguments,{'brightness':90});self.assertEqual(result.model_calls,0)
    async def test_relative_chain(self):
        conn,m,h=connection(decide=lambda _:decision(step('self_audio_speaker_set_volume',relative=10)))
        result=await h.run('大声点',[])
        self.assertEqual([x['tool'] for x in m.calls],['self_get_device_status','self_audio_speaker_set_volume'])
        self.assertEqual(result.results[-1].arguments,{'volume':60});self.assertNotIn('当前亮度',result.reply)
    async def test_exact_limit(self):
        _,m,h=connection(decide=lambda _:self.fail('unnecessary model'))
        result=await h.run('音量调到120',[])
        self.assertEqual(m.calls[-1]['arguments'],{'volume':100});self.assertEqual(result.results[-1].state,'completed')
    async def test_fake_success_repaired_once(self):
        decisions=iter([decision(mode='chat',reply='晚上十点的闹钟设好啦'),decision(step('alarm_set',{'hour':22,'minute':0,'label':'闹钟','repeat_days':0}))])
        _,m,h=connection(decide=lambda _:next(decisions))
        result=await h.run('给我定一个晚上十点的闹钟',[])
        self.assertEqual(result.repairs,1);self.assertEqual(result.results[-1].state,'completed')
    async def test_no_dispatch_no_success(self):
        _,m,h=connection(decide=lambda _:decision(mode='chat',reply='晚上十点的闹钟设好啦'))
        result=await h.run('给我定一个晚上十点的闹钟',[])
        self.assertFalse(m.calls);self.assertNotIn('设好啦',result.reply);self.assertEqual(result.repairs,1)
    async def test_wrong_receipt_unknown(self):
        _,m,h=connection();m.faults['self_audio_speaker_set_volume']=ActionResponse(Action.REQLLM,result={'ok':True,'volume':90})
        result=await h.run('把音量调到30',[])
        self.assertEqual(result.results[-1].state,'unknown');self.assertNotIn('已调到',result.reply)
    async def test_queued_not_complete(self):
        _,m,h=connection();m.faults['self_audio_speaker_set_volume']=ActionResponse(Action.REQLLM,result={'ok':True,'accepted':True,'volume':30})
        result=await h.run('把音量调到30',[])
        self.assertEqual(result.results[-1].state,'accepted');self.assertNotIn('已调到',result.reply)
    async def test_exception_no_retry(self):
        _,m,h=connection();m.faults['self_audio_speaker_set_volume']=RuntimeError('disconnect')
        result=await h.run('把音量调到30',[])
        self.assertEqual(len(m.calls),1);self.assertEqual(result.results[-1].state,'unknown')
    async def test_identity_change_stops(self):
        _,m,h=connection(decide=lambda _:decision(step('self_audio_speaker_set_volume',relative=10)))
        async def read(name,args):
            h.conn.person_turn=types.SimpleNamespace(key=('other','person',2))
            return ActionResponse(Action.REQLLM,result={'audio_speaker':{'output_volume':50},'screen':{'brightness':80}})
        m.faults['self_get_device_status']=read
        result=await h.run('大声点',[])
        self.assertEqual(len(m.calls),1);self.assertEqual(result.results[0].state,'completed');self.assertTrue(result.interrupted)
    async def test_bad_card_id_blocked(self):
        _,m,h=connection(decide=lambda _:decision(step('reminder_action',{'instance_id':'other-card','revision':2,'action':'primary'})))
        result=await h.run('完成当前卡片',[])
        self.assertNotIn('reminder_action',[x['tool'] for x in m.calls]);self.assertNotIn('已完成',result.reply)
    async def test_card_refs(self):
        first={'id':'read','tool':'reminder_get_current','arguments':{}}
        second={'id':'act','tool':'reminder_action','arguments':{'instance_id':{'$ref':{'step':'read','path':'instance_id'}},'revision':{'$ref':{'step':'read','path':'revision'}},'action':'primary'},'depends_on':['read']}
        _,m,h=connection(decide=lambda _:decision(first,second))
        result=await h.run('完成当前卡片',[])
        self.assertEqual(result.results[-1].state,'completed');self.assertEqual(m.calls[-1]['arguments']['instance_id'],'sim-card')
    async def test_whole_plan_validation_prevents_partial_write(self):
        _,m,h=connection(decide=lambda _:decision(step('alarm_set',{'hour':22,'minute':0,'label':'闹钟','repeat_days':0}),{'id':'b','tool':'self_audio_speaker_set_volume','arguments':{'volume':'invalid'}}))
        result=await h.run('设置晚上十点闹钟并设音量30',[])
        self.assertFalse(m.calls);self.assertEqual(result.repairs,1)
    async def test_duplicate_write_blocked(self):
        a=step('note_add',{'text':'买牛奶','remind_at':0});b={**a,'id':'b'}
        _,m,h=connection(decide=lambda _:decision(a,b))
        result=await h.run('记个便签买牛奶',[])
        self.assertEqual(len([x for x in m.calls if x['tool']=='note_add']),1)
    async def test_unavailable_entry(self):
        _,m,h=connection(decide=lambda _:decision(step('habit_create',{})))
        result=await h.run('创建习惯',[])
        self.assertFalse(m.calls);self.assertEqual(result.repairs,1)
    async def test_unreviewed_write_blocked(self):
        _,m,h=connection(decide=lambda _:decision(step('unknown_write',{})))
        d=copy.deepcopy(m.tools['note_add']);d.name='unknown_write';d.description['function']['name']='unknown_write';m.tools[d.name]=d
        result=await h.run('未知写操作',[]);self.assertFalse(m.calls)
    def test_ledger_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'ledger.sqlite');l=Ledger(path)
            self.assertTrue(l.reserve('s','t','note_add',{'text':'private-test'},'c'))
            self.assertFalse(l.reserve('s','t','note_add',{'text':'private-test'},'d'));l.close()
            l=Ledger(path);self.assertEqual(l.db.execute('SELECT state FROM dispatch').fetchone()[0],'unknown')
            self.assertNotIn(b'private-test',Path(path).read_bytes());l.close()
    def test_wrong_snooze_minutes(self):
        r=receipt('alarm_snooze',{'minutes':5},ActionResponse(Action.REQLLM,result='[ALARM_SNOOZED] 10'),'c');self.assertEqual(r.state,'unknown')
    def test_render_saved_options_match(self):
        r=receipt('self_screen_set_render_options',{'profile':'v1','spi_mhz':30,'pixel_diff':False},ActionResponse(Action.REQLLM,result={'ok':True,'requires_reboot':True,'next_boot_profile':'v2','next_boot_spi_mhz':30,'next_boot_pixel_diff':False}),'c');self.assertEqual(r.state,'unknown')
    def test_strict_decision(self):
        with self.assertRaises(Exception):Decision.model_validate({'mode':'operate','steps':[step('note_add',{},depends_on=['missing'])]})

    async def test_wrong_source_cannot_inherit_write_contract(self):
        _,m,h=connection(decide=lambda _:decision(step('note_add',{'text':'买牛奶','remind_at':0})))
        m.tools['note_add'].tool_type=ToolType.MCP_ENDPOINT
        out=await h.run('写个买牛奶便签',[]);self.assertFalse(m.calls)
        self.assertEqual(out.repairs,1)

    async def test_api_failure_has_no_model_retry(self):
        called=[]
        def failing(_):called.append(1);raise RuntimeError('simulated API failure')
        _,m,h=connection(decide=failing)
        out=await h.run('请定个晚上十点的闹钟',[])
        self.assertEqual(len(called),1);self.assertEqual(out.repairs,0);self.assertFalse(m.calls)

    async def test_negation_does_not_cancel_later_stop_command(self):
        _,m,h=connection(decide=lambda _:decision(step('reminder_stop_broadcast')))
        out=await h.run('先不要继续读提醒了，把播报停下，我们接着聊天。',[])
        self.assertEqual([x['tool'] for x in m.calls],['reminder_stop_broadcast'])
        self.assertEqual(out.results[-1].state,'completed')

    async def test_negative_continuation_is_stop_not_unrelated_write(self):
        _,m,h=connection(decide=lambda _:decision(step('self_audio_speaker_set_volume',{'volume':30})))
        out=await h.run('不要继续播报了',[])
        self.assertFalse(m.calls)
        self.assertEqual(out.repairs,1)
        _,m,h=connection(decide=lambda _:decision(step('reminder_stop_broadcast')))
        out=await h.run('不要继续播报了',[])
        self.assertEqual(out.results[-1].state,'completed')

    async def test_do_not_stop_broadcast_still_forbids_stop(self):
        _,m,h=connection(decide=lambda _:decision(step('reminder_stop_broadcast')))
        out=await h.run('不要停止播报',[])
        self.assertFalse(m.calls)
        self.assertEqual(out.mode,'chat')

    async def test_read_in_negation_not_sent(self):
        _,m,h=connection(decide=lambda _:decision(step('alarm_list')))
        out=await h.run('不要查看我设置的闹钟',[])
        self.assertFalse(m.calls);self.assertEqual(out.mode,'chat')

    async def test_reference_path_can_be_corrected_once(self):
        bad=[{'id':'read','tool':'memory_search','arguments':{'query':'喜欢咖啡'}},
             {'id':'forget','tool':'memory_forget','arguments':{'match':{'$ref':{'step':'read','path':'content'}}},'depends_on':['read']}]
        choices=iter([decision(*bad),decision(step('memory_forget',{'match':'喜欢咖啡'}))])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('忘掉喜欢咖啡的那条记忆',[])
        self.assertEqual(out.repairs,1);self.assertEqual(out.results[-1].state,'accepted')
        self.assertEqual(len([c for c in m.calls if c['tool']=='memory_forget']),1)

    async def test_queued_operation_captures_authority_before_lock(self):
        conn,m,h=connection()
        await h.lock.acquire()
        task=asyncio.create_task(h.run('把音量调到30',[]));await asyncio.sleep(0)
        conn.listen_epoch+=1;h.lock.release();out=await task
        self.assertFalse(m.calls);self.assertTrue(out.interrupted)

    async def test_chat_after_identity_change_not_spoken(self):
        conn,m,h=connection()
        def changed(_):conn.listen_epoch+=1;return decision(mode='chat',reply='你好')
        h.decide=changed;out=await h.run('你好',[])
        self.assertTrue(out.interrupted);self.assertFalse(m.calls)

    async def test_partial_failure_does_not_claim_second_success(self):
        _,m,h=connection();m.faults['self_screen_set_brightness']=ActionResponse(Action.REQLLM,result={'ok':True,'brightness':75})
        out=await h.run('把音量调到30，然后把亮度设为90',[])
        self.assertEqual([r.state for r in out.results],['completed','unknown'])
        self.assertIn('音量已调到30',out.reply);self.assertNotIn('亮度已调到90',out.reply)

    def test_face_start_requires_known_receipt(self):
        from core.utils.tool_result import require_enrollment_accepted
        self.assertEqual(require_enrollment_accepted('人脸录入已开始')['state'],'accepted')
        with self.assertRaises(Exception):require_enrollment_accepted('请求似乎成功了')

    async def test_tool_output_cannot_expand_write_authority(self):
        _,m,h=connection()
        h.decide=lambda _:decision(step('memory_search',{'query':'书'}),finished=False,authorized_writes=['note_add']) if not m.calls else decision(step('alarm_set',{'hour':22,'minute':0,'repeat_days':0,'label':'闹钟'}))
        out=await h.run('先查一下书的记忆然后记便签',[])
        self.assertNotIn('alarm_set',[c['tool'] for c in m.calls]);self.assertFalse([r for r in out.results if r.tool=='alarm_set'])

    async def test_relative_ignores_model_guessed_number(self):
        _,m,h=connection(decide=lambda _:decision(step('self_audio_speaker_set_volume',{'volume':99},relative=10)))
        out=await h.run('请让声音稍微大一点',[])
        self.assertEqual(out.results[-1].arguments,{'volume':60});self.assertEqual(m.volume,60)

    async def test_absolute_goal_cannot_be_replaced_with_relative(self):
        _,m,h=connection(decide=lambda _:decision(step('self_audio_speaker_set_volume',{'volume':30},relative=10)))
        h.fast_decision=lambda *a:None
        out=await h.run('现在麻烦把音量调到三十',[])
        self.assertFalse(m.calls)

    async def test_same_voice_request_not_dispatched_twice(self):
        from core.utils.person_identity import PersonTurn,activate,deactivate
        conn,m,h=connection();actor=PersonTurn('a','p',1,1,'personal','matched','same-request','sim','agent',1)
        conn.person_turn=actor;token=activate(conn,actor)
        try:
            first=await h.run('把音量调到30',[]);second=await h.run('把音量调到30',[])
        finally:deactivate(token)
        self.assertEqual(len(m.calls),1);self.assertEqual(first.results[-1].state,second.results[-1].state)

    async def test_catalog_raw_binding_change_stops_execution(self):
        conn,m,h=connection();conn.mcp_client=types.SimpleNamespace(name_mapping={'alarm_set':'alarm.set'},catalog_version=1)
        def changed(_):
            conn.mcp_client.name_mapping['alarm_set']='alarm_set';conn.mcp_client.catalog_version=2
            return decision(step('alarm_set',{'hour':22,'minute':0,'label':'闹钟','repeat_days':0}))
        h.decide=changed
        await h.run('帮我定个今晚十点的闹钟',[])
        self.assertFalse(m.calls)

    async def test_five_level_brightness_relative(self):
        _,m,h=connection()
        m.tools['self_screen_set_brightness'].description['function']['parameters']['properties']['brightness']['minimum']=1
        m.faults['self_get_device_status']=ActionResponse(Action.REQLLM,result={'screen':{'brightness':3,'brightness_level':3}})
        m.faults['self_screen_set_brightness']=ActionResponse(Action.REQLLM,result={'ok':True,'brightness':4,'brightness_level':4})
        out=await h.run('亮一点',[])
        self.assertEqual(out.results[-1].arguments,{'brightness':4});self.assertEqual(out.results[-1].state,'completed')

    async def test_alarm_delete_uses_position_not_persistent_id(self):
        _,m,h=connection(decide=lambda _:decision(step('alarm_delete',{'index':1})))
        m.faults['alarm_list']=ActionResponse(Action.REQLLM,result='[7] 22:00 闹钟 [仅一次]')
        out=await h.run('删除第一条闹钟',[])
        self.assertEqual(out.results[-1].state,'completed');self.assertEqual(m.calls[-1]['arguments'],{'index':1})

    async def test_wrong_weekend_bits_repaired_before_dispatch(self):
        decisions=iter([decision(step('alarm_set',{'hour':8,'minute':0,'label':'闹钟','repeat_days':96})),decision(step('alarm_set',{'hour':8,'minute':0,'label':'闹钟','repeat_days':65}))])
        _,m,h=connection(decide=lambda _:next(decisions))
        out=await h.run('每个周末早上八点闹钟叫醒我',[])
        self.assertEqual(out.repairs,1);self.assertEqual(len(m.calls),1)
        self.assertEqual(m.calls[0]['arguments']['repeat_days'],65)
        self.assertEqual(out.results[-1].state,'completed')

    async def test_completed_write_goal_stops_model_replanning(self):
        choices=iter([decision(step('self_get_device_status'),finished=False,authorized_writes=['self_audio_speaker_set_volume']),
                      decision(step('self_audio_speaker_set_volume',relative=10),finished=False,authorized_writes=['self_audio_speaker_set_volume'])])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('把声音轻轻调大一点',[])
        self.assertEqual(out.model_calls,2)
        self.assertEqual([c['arguments'] for c in m.calls if c['tool']=='self_audio_speaker_set_volume'],[{'volume':60}])
        self.assertEqual(out.reply,'音量已调到60。')

    async def test_relative_goal_cannot_become_minimum(self):
        choices=iter([decision(step('self_audio_speaker_set_volume',extreme='minimum')),decision(step('self_audio_speaker_set_volume',relative=10))])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('把声音轻轻调大一点',[])
        self.assertEqual(out.repairs,1)
        self.assertEqual(m.calls[-1]['arguments'],{'volume':60})
        self.assertEqual(len([c for c in m.calls if c['tool']=='self_audio_speaker_set_volume']),1)

    async def test_explicit_note_index_and_delay_do_not_need_clarification(self):
        choices=iter([decision(mode='clarify',reply='是哪一条？'),decision(step('note_snooze',{'index':1,'delay_minutes':8}))])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('第一条便签晚八分钟再提醒',[])
        self.assertEqual(out.repairs,1);self.assertEqual(out.results[-1].state,'completed')

    async def test_negative_chat_cannot_claim_execution(self):
        _,m,h=connection(decide=lambda _:decision(mode='chat',reply='闹钟已经设好啦'))
        out=await h.run('不要设置闹钟',[])
        self.assertFalse(m.calls);self.assertEqual(out.reply,'这次没有执行操作。')

    async def test_device_error_categories_preserved(self):
        for code,state in [('request_timeout','unknown'),('storage_full','failed'),('authentication_failed','failed')]:
            with self.subTest(code=code):
                ack=ActionResponse(Action.RESPONSE,result={'status':'error','errorCode':code,'message':'模拟错误'})
                r=receipt('note_add',{'text':'喝水','remind_at':0},ack,'rpc-id')
                self.assertEqual(r.state,state);self.assertEqual(r.error,code)

    async def test_weekend_once_or_repeat_requires_clarification(self):
        _,m,h=connection(decide=lambda _:self.fail('ambiguous calendar must not execute'))
        out=await h.run('周末早上八点闹钟叫醒我',[])
        self.assertEqual(out.mode,'clarify');self.assertFalse(m.calls)

    async def test_alarm_explicit_year_never_loses_date(self):
        _,m,h=connection(decide=lambda _:self.fail('unrepresentable date must not reach model executor'))
        out=await h.run('明年十月八号晚十点响闹钟',[])
        self.assertEqual(out.mode,'clarify');self.assertFalse(m.calls)

    async def test_schema_recall_uses_current_tool_names_within_budget(self):
        _,m,h=connection()
        for query,expected in [('忘掉我喜欢咖啡的记忆','memory_forget'),('看看记忆里我喜欢什么','memory_search'),('把显示配置的像素差分打开','self_screen_set_render_options'),('开始采集我的人脸','camera_face_enroll_start'),('将当前提醒标记完成','reminder_action')]:
            with self.subTest(query=query):
                messages=h.prompt([],h.catalog(),query)
                self.assertIn(expected,h.shown)
                self.assertLessEqual(len(h.shown),16)
                self.assertEqual(len(__import__('json').loads(messages[-1]['content'].split('[本轮可信目录与执行状态]\n')[1])['index']),45)

    async def test_live_optional_defaults_record_effective_arguments(self):
        args={'intent':'drink_water','description':'喝水','hour':8,'minute':0,'advance_minutes':2,'source':'auto'}
        _,m,h=connection(decide=lambda _:decision(step('habit_learn',args)))
        out=await h.run('保存每天八点喝水的习惯，提前两分钟',[])
        self.assertEqual(out.results[-1].state,'completed')
        self.assertEqual(out.results[-1].arguments['repeat_days'],127)
        self.assertEqual(m.calls[-1]['arguments']['repeat_days'],127)
        self.assertNotIn('repeat_days',args)

    async def test_declared_write_goal_cannot_stop_after_query(self):
        choices=iter([decision(step('self_get_device_status'),authorized_writes=['self_audio_speaker_set_volume']),decision(step('self_audio_speaker_set_volume',{},relative=10))])
        def decide(_):
            return next(choices,{'mode':'clarify','reply':'unexpected extra decision'})
        _,m,h=connection(decide=decide)
        out=await h.run('把声音往上加一些',[])
        self.assertEqual(out.repairs,1)
        self.assertEqual([c['tool'] for c in m.calls],['self_get_device_status','self_audio_speaker_set_volume'])
        self.assertEqual(m.calls[-1]['arguments']['volume'],60)
        self.assertNotIn('当前亮度',out.reply)

    async def test_chat_with_declared_write_requires_correction(self):
        choices=iter([decision(mode='chat',reply='安排上了',authorized_writes=['alarm_set']),decision(step('alarm_set',{'hour':22,'minute':0,'label':'闹钟','repeat_days':0}))])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('到晚上十点响铃叫我',[])
        self.assertEqual(out.repairs,1);self.assertEqual(m.calls[-1]['tool'],'alarm_set')
        self.assertNotIn('安排上了',out.reply)

    async def test_automatic_behavior_log_rejected_before_any_write(self):
        choices=iter([decision(step('handle_exit_intent',{'say_goodbye':'再见'}),{'id':'b','tool':'behavior_log','arguments':{'intent':'end_conversation','raw':'结束对话','outcome':'conversation'}}),decision(step('handle_exit_intent',{'say_goodbye':'再见'}))])
        _,m,h=connection(decide=lambda _:next(choices))
        h.prompt=lambda *a,**k:[];h.shown=set(m.tools)  # Both tools already have schemas.
        out=await h.run('现在请结束我们的对话',[])
        self.assertEqual(out.repairs,1)
        self.assertEqual([c['tool'] for c in m.calls],['handle_exit_intent'])
        self.assertNotIn('行为日志',out.reply)

    async def test_explicit_behavior_record_remains_available(self):
        _,m,h=connection(decide=lambda _:decision(step('behavior_log',{'intent':'drink_water','raw':'刚才喝水','outcome':'conversation'})))
        out=await h.run('把刚才喝水这件事记到行为记录里',[])
        self.assertEqual(out.results[-1].state,'completed')
        self.assertEqual(m.calls[-1]['tool'],'behavior_log')

    async def test_behavior_record_permission_is_not_a_noun_match(self):
        from core.utils.tool_harness.runtime import Harness
        for q in ['行为日志是什么意思','结束对话，不要记录行为日志','介绍一下行为记录']:
            self.assertFalse(Harness.behavior_record_requested(q))
        for q in ['给这次喝水留个行为记录','把刚才喝水这件事记到行为记录里','记录一次喝水行为日志']:
            self.assertTrue(Harness.behavior_record_requested(q))

    async def test_partial_reminder_parse_cannot_override_explicit_time(self):
        calls=[]
        def decide(_):
            calls.append(1)
            return decision(step('add_reminder',{'content':'取快递','remind_time_str':'十五分钟后'}))
        _,m,h=connection(decide=decide)
        out=await h.run('我怕忘记取快递，过十五分钟提醒我取快递。',[])
        self.assertTrue(calls)
        self.assertEqual(out.results[-1].state,'completed')
        self.assertEqual(m.calls[-1]['arguments'],{'content':'取快递','remind_time_str':'十五分钟后'})

    async def test_task_offer_is_not_a_claim_of_completed_execution(self):
        from core.utils.tool_harness.runtime import Harness
        for text in ['需要我为您设置一个提醒，以便在合适的时间继续完成报告正文吗？','需要我帮你设置一个提醒吗？']:
            self.assertFalse(Harness.claims_action(text))
        for text in ['晚上十点的闹钟设好啦','音量已经调好了','我已经帮你设置好了']:
            self.assertTrue(Harness.claims_action(text))

    async def test_negated_daily_repeat_does_not_override_one_shot(self):
        from core.utils.tool_harness.runtime import literal_constraints
        self.assertEqual(literal_constraints('今晚九点零五分让闹钟响一次，不要每天重复。')['alarm_set']['repeat_days'],0)
        self.assertEqual(literal_constraints('每天晚上九点闹钟响一次')['alarm_set']['repeat_days'],127)
        self.assertEqual(literal_constraints('工作日早晨六点响闹钟，不要每天重复')['alarm_set']['repeat_days'],62)
        _,m,h=connection(decide=lambda _:decision(step('alarm_set',{'hour':21,'minute':5,'label':'闹钟','repeat_days':0})))
        out=await h.run('今晚九点零五分让闹钟响一次，不要每天重复。',[])
        self.assertEqual(out.results[-1].state,'completed');self.assertEqual(len(m.calls),1)

    async def test_stop_broadcast_does_not_authorize_conversation_exit(self):
        choices=iter([decision(step('reminder_stop_broadcast'),{'id':'b','tool':'handle_exit_intent','arguments':{'say_goodbye':'再见'}}),decision(step('reminder_stop_broadcast'))])
        _,m,h=connection(decide=lambda _:next(choices))
        h.prompt=lambda *a,**k:[];h.shown=set(m.tools)
        out=await h.run('暂时别念待办了，退出播报就行。',[])
        self.assertEqual(out.repairs,1)
        self.assertEqual([c['tool'] for c in m.calls],['reminder_stop_broadcast'])
        from core.utils.tool_harness.runtime import Harness
        self.assertTrue(Harness.broadcast_only_exit('停止播报，不要结束对话'))
        self.assertFalse(Harness.broadcast_only_exit('停止播报，然后结束整个对话'))

    async def test_absolute_ratio_cannot_become_relative_delta(self):
        from core.utils.tool_harness.runtime import literal_constraints
        self.assertEqual(literal_constraints('亮度就用九成，帮我改一下')['self_screen_set_brightness']['brightness'],90)
        self.assertEqual(literal_constraints('把音量设成三成半')['self_audio_speaker_set_volume']['volume'],35)
        choices=iter([decision(step('self_screen_set_brightness',relative=90)),decision(step('self_screen_set_brightness',{'brightness':90}))])
        _,m,h=connection(decide=lambda _:next(choices))
        out=await h.run('亮度就用九成，帮我改一下',[])
        self.assertEqual(out.repairs,1);self.assertEqual(m.calls[-1]['arguments'],{'brightness':90})
        self.assertEqual([c['tool'] for c in m.calls],['self_screen_set_brightness'])

    async def test_multi_goal_missing_card_repaired_before_any_write(self):
        choices=iter([decision(step('self_audio_speaker_set_volume',{'volume':35})),decision(step('reminder_action',{'instance_id':'sim-card','revision':2,'action':'primary'}),{'id':'b','tool':'self_audio_speaker_set_volume','arguments':{'volume':35}})])
        _,m,h=connection(decide=lambda _:next(choices))
        h.prompt=lambda *a,**k:[];h.shown=set(m.tools)
        out=await h.run('做完当前提醒卡片，最后音量调到35',[])
        self.assertEqual(out.repairs,1)
        self.assertEqual([c['tool'] for c in m.calls],['reminder_get_current','reminder_action','self_audio_speaker_set_volume'])
        self.assertEqual(out.results[-1].state,'completed')

if __name__=='__main__':unittest.main(verbosity=2)
