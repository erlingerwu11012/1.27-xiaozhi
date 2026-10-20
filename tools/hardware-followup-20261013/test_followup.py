"""Targeted deterministic + real isolated HTTP regressions, no paid models."""
import bootstrap
from bootstrap import stage,budget
import concurrent.futures,dataclasses,json,time,types,unittest,uuid
from pathlib import Path
import requests,pymysql
from core.utils.tool_harness.models import Decision
from core.utils.tool_harness.request_authority import validate_authority,validate_memory_write
from core.utils.tool_harness.memory_policy import normalize_fact
from core.utils.device_speech_origin import note_device_speech,matches_device_speech
from core.utils.tool_harness.stream_decision import ReplyStream
from core.utils.person_identity import PersonTurn

API='http://127.0.0.1:18006/xiaozhi'
HEADERS={'Authorization':'Bearer '+(stage/'api-test-secret').read_text()}
ENV=json.loads((stage/'private-test-env.json').read_text())
assert ENV['PERSON_MEMORY_TEST_DATABASE']=='bailian_memory_test_followup20261013'

def sql(query,args=(),fetch=False):
    with pymysql.connect(host='127.0.0.1',user='root',password=ENV['PERSON_MEMORY_TEST_PASSWORD'],database=ENV['PERSON_MEMORY_TEST_DATABASE'],autocommit=True) as db:
        with db.cursor() as cursor:
            cursor.execute(query,args)
            return cursor.fetchall() if fetch else cursor.rowcount

class Followup(unittest.TestCase):
    def setUp(self):
        self.conn=types.SimpleNamespace(session_id='scope-a')
        info=requests.get(API+'/user-identities/internal/state/99003',headers=HEADERS,timeout=4).json()['data']
        self.actor=PersonTurn('99003',info['default_user_id'],info['default_generation'],info['directory_version'],'default','default',uuid.uuid4().hex,'test-device-http','agent_http',1,captured_at=int(time.time()*1000))
        for table in ['ai_agent_chat_history','ai_person_material','ai_memory_override']:
            sql('DELETE FROM '+table+' WHERE account_id=99003')
    def call(self,path,**body):
        self.actor=dataclasses.replace(self.actor,turn_id=uuid.uuid4().hex,captured_at=int(time.time()*1000))
        response=requests.post(API+'/person-memory/internal/'+path,headers=HEADERS,json={'actor':self.actor.payload(),**body},timeout=5)
        response.raise_for_status();value=response.json()
        self.assertEqual(value['code'],0,value.get('msg'));return value['data']
    def add(self,fact):return self.call('add',fact=fact)
    def read(self,ids):return self.call('recent',query='记录读回',recordIds=ids)
    def test_query_authority_rejects_dismiss(self):
        d=Decision(mode='operate',intent='action',intent_evidence='闹钟响了吗',authorized_writes=['alarm_dismiss'],steps=[{'id':'a','tool':'alarm_dismiss'}])
        with self.assertRaisesRegex(ValueError,'query_does_not'):validate_authority(d,'alarm_dismiss','闹钟响了吗','闹钟响了吗',self.conn)
    def test_negative_exit_is_not_a_goal(self):
        from core.utils.tool_harness.runtime import Harness
        self.assertNotIn('handle_exit_intent',Harness.write_targets('我没说要结束对话，继续聊。'))
        self.assertIn('handle_exit_intent',Harness.write_targets('结束对话。'))
    def test_pending_query_is_a_live_list_read(self):
        from core.utils.tool_harness.runtime import live_read_request,explicit_list_query
        self.assertEqual(live_read_request('查询待提醒的事项。'),'reminder_list_pending')
        self.assertIn('reminder_list_pending',explicit_list_query('当前有没有待提醒事项？'))
    def test_memory_fact_is_not_a_lexical_note_goal(self):
        from core.utils.tool_harness.runtime import Harness
        for query in ['记一下，我妈妈叫张敏。','记一下，我喜欢无糖豆浆。']:
            self.assertNotIn('note_add',Harness.write_targets(query))
        self.assertIn('note_add',Harness.write_targets('记个便签：买纸巾'))
    def test_verified_confirmation_scope(self):
        from core.utils.tool_harness.runtime import Harness
        from core.utils.tool_harness.models import OperationOutcome,StepResult
        h=object.__new__(Harness);h.scope=lambda:'a';h.last=None;h._user_request='存到记忆库里了吗？'
        r=StepResult(state='completed',tool='memory_add',call_id='x',arguments={'fact':'我爱喝美式'},reply='已保存',payload={'readback_confirmed':True})
        h.relevant_operation=('a',time.monotonic(),OperationOutcome(mode='operate',reply='',results=[r]),'save')
        self.assertFalse(h.unverified_action_claim('存好了。'))
        self.assertTrue(h.unverified_action_claim('全部记忆删除了。'))
        h.relevant_operation=('b',time.monotonic(),h.relevant_operation[2],'save')
        self.assertTrue(h.unverified_action_claim('存好了。'))
        h.relevant_operation=('a',time.monotonic()-91,h.relevant_operation[2],'save')
        self.assertTrue(h.unverified_action_claim('存好了。'))
        h.relevant_operation=('a',time.monotonic(),OperationOutcome(mode='operate',reply='',results=[r.model_copy(update={'state':'unknown'})]),'save')
        self.assertTrue(h.unverified_action_claim('存好了。'))
    def test_missing_semantic_fields_never_dispatch(self):
        d=Decision(mode='operate',authorized_writes=['memory_add'],steps=[{'id':'a','tool':'memory_add'}])
        with self.assertRaisesRegex(ValueError,'write_requires'):validate_authority(d,'memory_add','记一下我的偏好','记一下我的偏好',self.conn)
    def test_save_synonym_uses_semantic_evidence(self):
        for text in ['那你记一下','存到记忆库里吧','给我存进去']:
            d=Decision(mode='operate',intent='action',intent_evidence=text,authorized_writes=['memory_add'],steps=[{'id':'a','tool':'memory_add','arguments':{'fact':'我的配偶叫测试甲'}}])
            validate_authority(d,'memory_add',text,text,self.conn)
    def test_unquoted_evidence_rejected(self):
        d=Decision(mode='operate',intent='action',intent_evidence='删除全部个人记忆',authorized_writes=['memory_forget'],steps=[{'id':'a','tool':'memory_forget'}])
        with self.assertRaises(ValueError):validate_authority(d,'memory_forget','我爱喝什么','我爱喝什么',self.conn)
    def test_wildcard_deictic_is_blocked(self):
        for text in ['把这些记忆全删除了','刚才查到的饮品全部删了','这些全部忘掉']:
            with self.assertRaisesRegex(ValueError,'explicit_store_scope'):validate_memory_write('memory_forget',{'match':'*'},text)
        validate_memory_write('memory_forget',{'match':'*'},'清空全部个人记忆')
    def test_relation_must_survive_correction(self):
        with self.assertRaisesRegex(ValueError,'loses_relationship'):validate_memory_write('memory_correct',{'match':'我的配偶叫测试甲','replacement':'测试乙'},'改成测试乙')
        validate_memory_write('memory_correct',{'match':'我的配偶叫测试甲','replacement':'我的配偶叫测试乙'},'改成测试乙')
    def test_instruction_filter_and_fact_extraction(self):
        for text in ['你存到记忆库里吧','把这些记忆全删除了','行，待机吧','你记好啊']:
            self.assertEqual(normalize_fact(text),'',text)
        self.assertEqual(normalize_fact('那你记一下，我老婆叫测试甲'),'我老婆叫测试甲')
    def test_echo_scope_and_expiry(self):
        note_device_speech(self.conn,'提醒你拿外卖。',source='reminder',now=10)
        self.assertTrue(matches_device_speech(self.conn,'提醒你拿外卖',now=11))
        self.assertFalse(matches_device_speech(self.conn,'我拿到外卖了',now=11))
        self.assertFalse(matches_device_speech(self.conn,'提醒你拿外卖',now=31))
        self.conn.session_id='scope-b';self.assertFalse(matches_device_speech(self.conn,'提醒你拿外卖',now=11))
    def test_json_fragment_control_fields(self):
        updates=[];parser=ReplyStream(updates.append)
        payload=json.dumps({'mode':'chat','steps':[],'authorized_writes':[],'intent':'chat','intent_evidence':'','reply':'名字里的引号是“甲”。再接一句。'},ensure_ascii=True)
        for character in payload:parser.feed(character)
        self.assertEqual(parser.finish()['reply'],updates[-1])
    def test_json_operation_never_speaks_early(self):
        updates=[];parser=ReplyStream(updates.append)
        for part in ['{"mode":"operate","steps":[', '{"id":"a","tool":"memory_add","arguments":{"fact":"我的配偶叫测试甲"}}],', '"authorized_writes":["memory_add"],"reply":"存好了"}']:parser.feed(part)
        parser.finish();self.assertEqual(updates,[])
    def test_save_readback_by_id_and_version(self):
        saved=self.add('我的配偶叫测试甲');read=self.read([saved['record_id']])
        self.assertEqual([(x['record_id'],x['text'],x['version']) for x in read['items']],[(saved['record_id'],'我的配偶叫测试甲',saved['version'])])
    def test_scoped_forget_preserves_other_fact(self):
        drinks=[self.add('我爱喝美式咖啡'),self.add('我爱喝普洱茶')];spouse=self.add('我的配偶叫测试甲')
        targets=[{'recordId':x['record_id'],'expectedVersion':x['version'],'match':x['fact']} for x in drinks]
        result=self.call('forget-records',records=targets);self.assertTrue(result['ok'])
        read=self.read([x['record_id'] for x in drinks]+[spouse['record_id']])
        self.assertEqual([x['text'] for x in read['items']],['我的配偶叫测试甲'])
    def test_partial_forget_reports_each_record(self):
        facts=[self.add('我爱喝美式咖啡'),self.add('我的配偶叫测试甲')]
        result=self.call('forget-records',records=[{'recordId':x['record_id'],'expectedVersion':x['version'] if i==0 else 'stale','match':x['fact']} for i,x in enumerate(facts)])
        self.assertEqual(result['status'],'partial');self.assertFalse(result['ok'])
        self.assertEqual([x['text'] for x in self.read([x['record_id'] for x in facts])['items']],['我的配偶叫测试甲'])
    def test_correction_new_record_readback(self):
        fact=self.add('我的配偶叫测试甲')
        changed=self.call('override',action='correct',recordId=fact['record_id'],expectedVersion=fact['version'],match=fact['fact'],replacement='我的配偶叫测试乙')
        read=self.read([fact['record_id'],changed['record_id']]);self.assertEqual([x['text'] for x in read['items']],['我的配偶叫测试乙'])
        self.assertEqual(read['items'][0]['version'],changed['version'])
    def test_persistent_list_pagination(self):
        for i in range(10):self.add('我的测试偏好编号是'+str(i))
        first=self.call('recent',query='我的事实',scope='facts',page=1);second=self.call('recent',query='我的事实',scope='facts',page=2)
        self.assertEqual(len(first['items']),8);self.assertEqual(len(second['items']),2)
        self.assertTrue(first['has_more']);self.assertFalse(first['total_complete'])
        self.assertFalse(set(x['record_id'] for x in first['items']) & set(x['record_id'] for x in second['items']))
    def test_related_drink_scope_excludes_spouse(self):
        drink=self.add('我最爱美式咖啡');self.add('我妻子叫测试甲')
        for query in ['我爱喝什么','我的饮品偏好','我的咖啡相关偏好']:
            found=self.call('recent',query=query)
            self.assertEqual([x['record_id'] for x in found['items']],[drink['record_id']],query)
    def test_archive_commands_excluded(self):
        for text in ['你存到记忆库里吧','把这些记忆全删除了','行，待机吧','存到记忆库里了吗？']:
            sql("INSERT INTO ai_agent_chat_history(account_id,person_id,agent_id,default_generation,recall_allowed,chat_type,content,created_at) VALUES(99003,%s,'agent_http',%s,TRUE,1,%s,NOW())",(self.actor.person_id,self.actor.generation,text))
        result=self.call('recent',query='记忆库');self.assertEqual(result['items'],[])
    def test_history_parallel_idempotence(self):
        sql("UPDATE ai_agent SET chat_history_conf=1 WHERE id='agent_http' AND user_id=99003")
        event='followup-'+uuid.uuid4().hex
        payload={'macAddress':'test-device-http','sessionId':'isolated-session','chatType':2,'content':'自动化隔离历史内容','reportTime':int(time.time()),'identity':self.actor.payload(),'eventId':event,'turnId':self.actor.turn_id}
        def send(_):return requests.post(API+'/agent/chat-history/report',headers=HEADERS,json=payload,timeout=10).json()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:responses=list(pool.map(send,range(16)))
        self.assertTrue(all(x.get('code')==0 for x in responses),[x.get('msg') for x in responses])
        count=sql('SELECT count(*) FROM ai_agent_chat_history WHERE account_id=99003 AND event_id=%s',(event,),True)
        self.assertEqual(count[0][0],1)

class BudgetResult(unittest.TextTestResult):
    def startTest(self,test):
        self.charge=budget.reserve('case',test.id());super().startTest(test)
    def stopTest(self,test):
        error=next((str(trace) for case,trace in self.errors+self.failures if case==test),None)
        metadata={'test':test.id(),'passed':error is None,'error':error}
        budget.finish(self.charge,metadata)
        with (stage/'deterministic-results.jsonl').open('a') as out:out.write(json.dumps(metadata,ensure_ascii=False)+'\n')
        super().stopTest(test)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(Followup))
    raise SystemExit(not result.wasSuccessful())
