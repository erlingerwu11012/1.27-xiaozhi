package ali

import (
	"encoding/json"
	"github.com/songquanpeng/one-api/relay/model"
	"testing"
)

func TestExplicitQwenThinkingModeSurvivesGateway(t *testing.T) {
	for _, mode := range []bool{false, true} {
		raw, _ := json.Marshal(map[string]interface{}{"model": "qwen-plus", "enable_thinking": mode})
		var request model.GeneralOpenAIRequest
		if e := json.Unmarshal(raw, &request); e != nil {
			t.Fatal(e)
		}
		result := ConvertRequest(request)
		if result.Parameters.EnableThinking == nil || *result.Parameters.EnableThinking != mode {
			t.Fatal("thinking mode was dropped")
		}
		encoded, _ := json.Marshal(result)
		var body map[string]interface{}
		json.Unmarshal(encoded, &body)
		if body["parameters"].(map[string]interface{})["enable_thinking"] != mode {
			t.Fatal("false omitted")
		}
	}
	if ConvertRequest(model.GeneralOpenAIRequest{Model: "qwen-plus"}).Parameters.EnableThinking != nil {
		t.Fatal("legacy default changed")
	}
}
