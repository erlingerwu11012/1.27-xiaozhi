package bailian

import (
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"sync"

	"github.com/gorilla/websocket"
)

type strictFake struct {
	mu         sync.Mutex
	createN    int
	queryN     int
	deleteN    int
	synthN     int
	rejected   int
	lastClone  []byte
	lastQuery  []byte
	lastSynth  []byte
	deleted    []string
	lastRun    map[string]interface{}
	lastAuth   string
	lastWSAuth string
	wsN        int
	voices     map[string]map[string]string
	mode       string
}

func newStrictFake() *strictFake {
	return &strictFake{
		voices: map[string]map[string]string{
			"importvoice01": {"status": StatusOK, "target_model": TargetTTSPlus},
		},
	}
}

func (f *strictFake) handler() http.Handler {
	up := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if websocket.IsWebSocketUpgrade(r) {
			f.mu.Lock()
			f.wsN++
			f.lastWSAuth = r.Header.Get("Authorization")
			f.mu.Unlock()
			c, err := up.Upgrade(w, r, nil)
			if err != nil {
				return
			}
			defer c.Close()
			_, data, err := c.ReadMessage()
			if err != nil {
				return
			}
			var ev map[string]interface{}
			_ = json.Unmarshal(data, &ev)
			if reason := unofficialHotFixFromWS(ev); reason != "" {
				f.mu.Lock()
				f.rejected++
				f.mu.Unlock()
				return
			}
			if reason := unofficialBitRateFromWS(ev); reason != "" {
				f.mu.Lock()
				f.rejected++
				f.mu.Unlock()
				return
			}
			f.mu.Lock()
			f.lastRun = ev
			f.mu.Unlock()
			taskID := ""
			if h, ok := ev["header"].(map[string]interface{}); ok {
				taskID, _ = h["task_id"].(string)
			}
			_ = c.WriteMessage(1, []byte(`{"header":{"event":"task-started","task_id":"`+taskID+`"}}`))
			for {
				kind, payload, err := c.ReadMessage()
				if err != nil {
					return
				}
				if kind != 1 {
					continue
				}
				var next map[string]interface{}
				_ = json.Unmarshal(payload, &next)
				h, _ := next["header"].(map[string]interface{})
				action, _ := h["action"].(string)
				if action == "continue-task" {
					_ = c.WriteMessage(2, []byte{0, 1})
					continue
				}
				if action == "finish-task" {
					fin, _ := json.Marshal(map[string]interface{}{
						"header":  map[string]string{"event": "task-finished", "task_id": taskID},
						"payload": map[string]interface{}{"usage": map[string]int64{"characters": 4}},
					})
					_ = c.WriteMessage(1, fin)
					return
				}
			}
		}
		body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		f.mu.Lock()
		f.lastAuth = r.Header.Get("Authorization")
		f.mu.Unlock()
		reject := func(code int, msg string) {
			f.mu.Lock()
			f.rejected++
			f.mu.Unlock()
			http.Error(w, msg, code)
		}
		switch {
		case r.Method == "POST" && r.URL.Path == HTTPPathCustomization:
			var env enrollmentEnvelope
			if json.Unmarshal(body, &env) != nil || env.Model != EnrollmentModel || env.Input.Action == "" {
				reject(400, "invalid_enrollment")
				return
			}
			rawMap := map[string]interface{}{}
			_ = json.Unmarshal(body, &rawMap)
			if input, _ := rawMap["input"].(map[string]interface{}); input != nil {
				if _, ok := input["operation"]; ok {
					reject(400, "unofficial_operation_field")
					return
				}
				if _, ok := input["idempotency_key"]; ok {
					reject(400, "unofficial_idempotency_field")
					return
				}
				if _, ok := input["voice"]; ok {
					reject(400, "qwen_tts_voice_field_not_allowed")
					return
				}
			}
			switch env.Input.Action {
			case ActionCreateVoice:
				isDesign := env.Input.VoicePrompt != ""
				if isDesign {
					if env.Input.PreviewText == "" || env.Input.URL != "" {
						reject(400, "design_requires_preview_not_url")
						return
					}
				} else if env.Input.URL == "" || env.Input.Prefix == "" || env.Input.TargetModel != TargetTTSPlus {
					reject(400, "clone_fields_required")
					return
				}
				f.mu.Lock()
				f.createN++
				f.lastClone = append([]byte(nil), body...)
				voiceID := "clonedvoice01"
				if isDesign {
					voiceID = "designedvoice01"
				}
				if f.voices == nil {
					f.voices = map[string]map[string]string{}
				}
				st := StatusOK
				if f.mode == "deploying" {
					st = StatusDeploying
				}
				f.voices[voiceID] = map[string]string{"status": st, "target_model": TargetTTSPlus}
				f.mu.Unlock()
				if f.mode == "missing_voice_id" {
					w.Header().Set("Content-Type", "application/json")
					_, _ = w.Write([]byte(`{"output":{"status":"OK"}}`))
					return
				}
				if f.mode == "500" {
					reject(500, "upstream_5xx")
					return
				}
				if f.mode == "429" {
					reject(429, "rate_limited")
					return
				}
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(map[string]interface{}{
					"request_id": "req-create",
					"output":     map[string]string{"voice_id": voiceID},
					"usage":      map[string]int{"count": 1},
				})
			case ActionQueryVoice:
				if env.Input.VoiceID == "" {
					reject(400, "voice_id_required")
					return
				}
				f.mu.Lock()
				f.queryN++
				f.lastQuery = append([]byte(nil), body...)
				row := f.voices[env.Input.VoiceID]
				mode := f.mode
				f.mu.Unlock()
				if row == nil {
					http.NotFound(w, r)
					return
				}
				if mode == "missing_status" {
					w.Header().Set("Content-Type", "application/json")
					_ = json.NewEncoder(w).Encode(map[string]interface{}{"output": map[string]string{"voice_id": env.Input.VoiceID}})
					return
				}
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(map[string]interface{}{
					"request_id": "req-query",
					"output": map[string]string{
						"status": row["status"], "target_model": row["target_model"],
						"voice_id": env.Input.VoiceID, "gmt_create": "2026-09-18 00:00:00",
					},
				})
			case ActionDeleteVoice:
				if env.Input.VoiceID == "" {
					reject(400, "voice_id_required")
					return
				}
				f.mu.Lock()
				f.deleteN++
				f.deleted = append(f.deleted, env.Input.VoiceID)
				delete(f.voices, env.Input.VoiceID)
				f.mu.Unlock()
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(`{"request_id":"req-del","output":{}}`))
			default:
				reject(400, "unknown_action")
			}
		case r.Method == "POST" && r.URL.Path == HTTPPathSpeechSynthesizer:
			var parsed struct {
				Model string `json:"model"`
				Input struct {
					Text        string   `json:"text"`
					Voice       string   `json:"voice"`
					Format      string   `json:"format"`
					Instruction string   `json:"instruction"`
					Hints       []string `json:"language_hints"`
				} `json:"input"`
			}
			if json.Unmarshal(body, &parsed) != nil || parsed.Model != TargetTTSPlus || parsed.Input.Text == "" || parsed.Input.Voice == "" {
				reject(400, "invalid_synth")
				return
			}
			var envelope map[string]interface{}
			_ = json.Unmarshal(body, &envelope)
			if reason := unofficialHotFixFromHTTP(envelope); reason != "" {
				reject(400, reason)
				return
			}
			if reason := unofficialBitRateFromHTTP(envelope); reason != "" {
				reject(400, reason)
				return
			}
			f.mu.Lock()
			f.synthN++
			f.lastSynth = append([]byte(nil), body...)
			f.mu.Unlock()
			wav := SilentPCM16Wav(1, 16000)
			chars, _ := TTSCharacters(parsed.Input.Text, false)
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"request_id": "req-synth",
				"output": map[string]interface{}{
					"finish_reason": "stop",
					"audio":         map[string]string{"data": base64.StdEncoding.EncodeToString(wav)},
				},
				"usage": map[string]int64{"characters": chars},
			})
		default:
			reject(404, "unsupported_official_path")
		}
	})
}

func unofficialHotFixReason(raw json.RawMessage) string {
	if len(raw) == 0 || string(raw) == "null" {
		return ""
	}
	if HotFixIsOfficialWire(raw) {
		return ""
	}
	return "hot_fix_unofficial"
}

func unofficialHotFixFromHTTP(envelope map[string]interface{}) string {
	input, _ := envelope["input"].(map[string]interface{})
	if input == nil {
		return ""
	}
	hf, ok := input["hot_fix"]
	if !ok {
		return ""
	}
	raw, _ := json.Marshal(hf)
	return unofficialHotFixReason(raw)
}

func unofficialHotFixFromWS(ev map[string]interface{}) string {
	payload, _ := ev["payload"].(map[string]interface{})
	if payload == nil {
		return ""
	}
	params, _ := payload["parameters"].(map[string]interface{})
	if params == nil {
		return ""
	}
	hf, ok := params["hot_fix"]
	if !ok {
		return ""
	}
	raw, _ := json.Marshal(hf)
	return unofficialHotFixReason(raw)
}

func unofficialBitRateFromMap(format string, br interface{}) string {
	if br == nil {
		return ""
	}
	if format != "opus" {
		return "bit_rate_format"
	}
	n, ok := br.(float64)
	if !ok {
		return "invalid_bit_rate"
	}
	v := int(n)
	if v < 6 || v > 510 {
		return "invalid_bit_rate"
	}
	return ""
}

func unofficialBitRateFromHTTP(envelope map[string]interface{}) string {
	input, _ := envelope["input"].(map[string]interface{})
	if input == nil {
		return ""
	}
	format, _ := input["format"].(string)
	return unofficialBitRateFromMap(format, input["bit_rate"])
}

func unofficialBitRateFromWS(ev map[string]interface{}) string {
	payload, _ := ev["payload"].(map[string]interface{})
	if payload == nil {
		return ""
	}
	params, _ := payload["parameters"].(map[string]interface{})
	if params == nil {
		return ""
	}
	format, _ := params["format"].(string)
	return unofficialBitRateFromMap(format, params["bit_rate"])
}
