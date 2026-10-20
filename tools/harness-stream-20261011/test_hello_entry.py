"""Host-test the exact production ParseServerHello body through RX dispatch."""
from pathlib import Path
import importlib.util,subprocess,json
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('host',ROOT/'tools/run_websocket_rx_gate_host_test.py')
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
source=(ROOT/'main/protocols/websocket_protocol.cc').read_text(encoding='utf8')
body=source[source.index('void WebsocketProtocol::ParseServerHello('):]
body=body[:body.index('\n}',body.index('{'))+2]
opening=source[source.index('bool WebsocketProtocol::OpenAudioChannel('):source.index('void WebsocketProtocol::ParseServerHello(')]
assert opening.index('xEventGroupClearBits')<opening.index('BeginConnection')
out=ROOT/'build/host_tests';out.mkdir(parents=True,exist_ok=True)
cpp=out/'test_hello_entry.cpp'
cpp.write_text(r'''
#include <string>
#include <cstring>
#include <cassert>
#include <cstdint>
#include <cJSON.h>
#include "websocket_connection_gate.h"
#include "vision_credentials.h"
#include "esp_log.h"
static int ready=0;
static const int WEBSOCKET_PROTOCOL_SERVER_HELLO_EVENT=1;
static const char* TAG="host";
static void xEventGroupSetBits(void*,int) {++ready;}
struct FaceRoster {static FaceRoster& GetInstance(){static FaceRoster x;return x;} void OnAudioSessionOpened(std::string) {}};
struct WebsocketProtocol {std::string session_id_;int server_sample_rate_=0,server_frame_duration_=0;void* event_group_handle_=nullptr;void ParseServerHello(const cJSON*,uint32_t);};
'''+body+r'''
int main(){
 auto& store=VisionCredentialStore::GetInstance();WebsocketConnectionGate gate;WebsocketProtocol protocol;
 auto gen=store.BeginConnection();gate.Begin(gen,&protocol.session_id_);
 auto rx=[&](uint32_t g,const char* s){WebsocketTextDispatchHandlers h;h.on_hello=[&](const cJSON* p){protocol.ParseServerHello(p,g);};return DispatchWebsocketTextFrame(gate,g,s,strlen(s),h);};
 store.ApplyInitializeVision(gen,"https://example.test/explain","https://example.test/identify","test-token","",0);
 VisionCredentialSnapshot snap;assert(!store.TryAcquireExplainSnapshot(&snap));
 rx(gen,"{\"type\":\"hello\",\"transport\":\"websocket\",\"session_id\":\"session-one\"}");
 assert(ready==1&&protocol.session_id_=="session-one");assert(store.TryAcquireExplainSnapshot(&snap)&&snap.session_id=="session-one");
 auto next=store.BeginConnection();gate.Begin(next,&protocol.session_id_);ready=0;
 rx(gen,"{\"type\":\"hello\",\"transport\":\"websocket\",\"session_id\":\"old\"}");assert(ready==0&&protocol.session_id_.empty());
 rx(next,"{\"type\":\"hello\",\"session_id\":\"bad\"}");assert(ready==0);
 rx(next,"{\"type\":\"hello\",\"transport\":\"websocket\",\"session_id\":\"\"}");assert(ready==0);
 rx(next,"{\"type\":\"hello\",\"transport\":\"websocket\",\"session_id\":\"session-two\"}");assert(ready==1);
 assert(!store.TryAcquireExplainSnapshot(&snap));
 store.ApplyInitializeVision(next,"https://example.test/explain","https://example.test/identify","second-token","",0);
 assert(store.TryAcquireExplainSnapshot(&snap)&&snap.session_id=="session-two"&&snap.token=="second-token");
 store.ApplyInitializeVision(gen,"https://example.test/explain","https://example.test/identify","stale-token","",0);
 assert(store.TryAcquireExplainSnapshot(&snap)&&snap.token=="second-token");
 gate.End(next,&protocol.session_id_);store.EndConnection(next);
 rx(next,"{\"type\":\"hello\",\"transport\":\"websocket\",\"session_id\":\"closed\"}");assert(protocol.session_id_.empty());
}
''',encoding='utf8')
compiler=host.find_compiler();assert compiler
subprocess.run([compiler,'-std=c++17','-O1','-pthread',f'-I{host.MAIN}',f'-I{host.MAIN / "protocols"}',f'-I{out}',f'-I{host.CJSON_INC}',str(cpp),str(host.GATE_CC),str(host.VISION_CC),str(host.CJSON_C),'-o',str(out/'test_hello_entry.exe')],check=True)
subprocess.run([str(out/'test_hello_entry.exe')],check=True)
print(json.dumps({'passed':10,'source':'exact ParseServerHello via production RX gate; stale-ready clearing order verified','hardware':False}))
