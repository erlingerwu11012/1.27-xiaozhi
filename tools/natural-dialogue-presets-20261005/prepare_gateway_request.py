from pathlib import Path
root=Path('/root/prjs/tmp/natural-dialogue-presets-20261005/gateway-candidate')
p=root/'relay/model/general.go'
text=p.read_text()
line='EnableThinking *bool `json:"enable_thinking,omitempty"`'
assert text.count(line)==1
text=text.replace(line,line+'\n PreserveThinking *bool `json:"preserve_thinking,omitempty"`',1)
p.write_text(text)
(root/'relay/model/qwen38_request_test.go').write_text('''package model
import("encoding/json"; "testing")
func TestQwen38NonThinkingParametersSurviveRelay(t *testing.T) {
 var req GeneralOpenAIRequest
 if e:=json.Unmarshal([]byte(`{"model":"qwen3.8-flash","enable_thinking":false,"preserve_thinking":false}`), &req); e!=nil {t.Fatal(e)}
 raw,e:=json.Marshal(req);if e!=nil {t.Fatal(e)}
 var got map[string]any
 if e=json.Unmarshal(raw,&got);e!=nil {t.Fatal(e)}
 for _, key:=range []string{"enable_thinking","preserve_thinking"} {if value,ok:=got[key];!ok || value!=false {t.Fatalf("%s dropped or altered",key)}}
}
''')
print('Qwen3.8 request fields preserved')
