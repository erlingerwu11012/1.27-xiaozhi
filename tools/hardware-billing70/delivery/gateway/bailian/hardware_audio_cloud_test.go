//go:build cloud_hardware_audio

package bailian

import (
	"encoding/base64"
	"encoding/json"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/songquanpeng/one-api/hardwarebilling"
	"github.com/songquanpeng/one-api/model"
	"net/http"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Full token authentication and signed WebSocket entry, real upstream, temporary
// SQLite wallet only. Synthetic PCM stays in memory and is discarded afterwards.
func TestHardwareAudioRealCloudAndLedger(t *testing.T) {
	key := os.Getenv("CLOUD_HW_AUDIO_KEY")
	if key == "" || os.Getenv("CLOUD_HW_AUTHORIZED") != "1" {
		t.Fatal("explicit isolated cloud authorization required")
	}
	t.Setenv("HW_BILLING_ENABLED", "1")
	secret := strings.Repeat("s", 32)
	t.Setenv("HW_BILLING_SERVICE_KEY", secret)
	base := os.Getenv("CLOUD_HW_AUDIO_BASE")
	if base == "" {
		base = "https://dashscope.aliyuncs.com"
	}
	db := openTestDB(t)
	pool, e := db.DB()
	if e != nil {
		t.Fatal(e)
	}
	pool.SetMaxOpenConns(1)
	token, _ := seedGateway(t, db, base)
	models := "qwen-audio-3.0-tts-plus,qwen3-asr-flash-realtime"
	if e := db.Model(&model.Channel{}).Where("id=1").Updates(map[string]interface{}{"key": key, "models": models}).Error; e != nil {
		t.Fatal(e)
	}
	if e := db.Model(&model.Token{}).Where("id=1").Update("models", models).Error; e != nil {
		t.Fatal(e)
	}
	priceASR := `{"version":"official-cn-beijing-20261001","region":"cn-beijing","cny_per_unit":"0.00033","unit":"audio_second","model_multiplier":"1.43","group_multiplier":"1","quota_per_usd":"500000","cny_per_usd":"7.2"}`
	if e := db.Create(&Capability{Model: "qwen3-asr-flash-realtime", Region: "cn-beijing", Protocol: "asr_realtime", Path: "/api-ws/v1/realtime", PriceJSON: priceASR, Enabled: true, Verified: true}).Error; e != nil {
		t.Fatal(e)
	}
	l := hardwarebilling.Ledger{DB: db}
	if e := l.Migrate(); e != nil {
		t.Fatal(e)
	}
	if e := l.Bootstrap(1, "99018001", 0); e != nil {
		t.Fatal(e)
	}
	if e := l.Recharge(1, "audio-cloud", 100, 100); e != nil {
		t.Fatal(e)
	}
	gw := startGateway(t, db)
	connect := func(path, op, id string) *websocket.Conn {
		proof := hardwarebilling.ServiceProof{Timestamp: strconv.FormatInt(time.Now().Unix(), 10), RequestID: id, ProductAccount: "99018001", Operation: op}
		sig, e := hardwarebilling.SignProof([]byte(secret), "GET", path, nil, proof)
		if e != nil {
			t.Fatal(e)
		}
		h := http.Header{"Authorization": {"Bearer sk-" + token}, "X-HW-Account": {proof.ProductAccount}, "X-HW-Operation": {op}, "X-HW-Request-ID": {id}, "X-HW-Timestamp": {proof.Timestamp}, "X-HW-Signature": {sig}}
		ws, _, e := websocket.DefaultDialer.Dial(strings.Replace(gw, "http:", "ws:", 1)+path, h)
		if e != nil {
			t.Fatal(e)
		}
		ws.SetReadDeadline(time.Now().Add(45 * time.Second))
		return ws
	}
	send := func(ws *websocket.Conn, msg interface{}) {
		raw, e := json.Marshal(msg)
		if e != nil {
			t.Fatal(e)
		}
		if e = ws.WriteMessage(1, raw); e != nil {
			t.Fatal(e)
		}
	}
	read := func(ws *websocket.Conn) (int, []byte, map[string]interface{}) {
		kind, raw, e := ws.ReadMessage()
		if e != nil {
			t.Fatal(e)
		}
		var msg map[string]interface{}
		if kind == 1 {
			if e = json.Unmarshal(raw, &msg); e != nil {
				t.Fatal(e)
			}
			if msg["type"] == "error" {
				detail, _ := msg["error"].(map[string]interface{})
				t.Fatalf("gateway audio error code=%v", detail["code"])
			}
		}
		return kind, raw, msg
	}
	task := uuid.NewString()
	pcm := []byte{}
	ws := connect("/bailian/api-ws/v1/inference?model=qwen-audio-3.0-tts-plus", "tts", "audio-real-tts")
	send(ws, map[string]interface{}{"header": map[string]string{"action": "run-task", "task_id": task, "streaming": "duplex"}, "payload": map[string]interface{}{"task_group": "audio", "task": "tts", "function": "SpeechSynthesizer", "model": "qwen-audio-3.0-tts-plus", "parameters": map[string]interface{}{"text_type": "PlainText", "voice": "longanlingxi", "format": "pcm", "sample_rate": 16000, "volume": 50, "rate": 1, "pitch": 1}, "input": map[string]interface{}{}}})
	for {
		kind, raw, msg := read(ws)
		if kind == 2 {
			pcm = append(pcm, raw...)
			continue
		}
		header, _ := msg["header"].(map[string]interface{})
		event, _ := header["event"].(string)
		if event == "task-started" {
			send(ws, map[string]interface{}{"header": map[string]string{"action": "continue-task", "task_id": task, "streaming": "duplex"}, "payload": map[string]interface{}{"input": map[string]string{"text": "测试用语，请把音量调到百分之三十。"}}})
			send(ws, map[string]interface{}{"header": map[string]string{"action": "finish-task", "task_id": task, "streaming": "duplex"}, "payload": map[string]interface{}{"input": map[string]interface{}{}}})
		}
		if event == "task-failed" {
			t.Fatal("real TTS task failed")
		}
		if event == "task-finished" {
			break
		}
	}
	ws.Close()
	if len(pcm) == 0 {
		t.Fatal("no synthetic PCM")
	}
	ws = connect("/bailian/api-ws/v1/realtime?model=qwen3-asr-flash-realtime", "asr", "audio-real-asr")
	recognized := false
	for {
		_, _, msg := read(ws)
		typ, _ := msg["type"].(string)
		if typ == "session.created" {
			send(ws, map[string]interface{}{"type": "session.update", "session": map[string]interface{}{"modalities": []string{"text"}, "input_audio_format": "pcm", "sample_rate": 16000, "turn_detection": nil, "input_audio_transcription": map[string]string{"language": "zh"}}})
		}
		if typ == "session.updated" {
			for start := 0; start < len(pcm); start += 3200 {
				end := start + 3200
				if end > len(pcm) {
					end = len(pcm)
				}
				send(ws, map[string]string{"type": "input_audio_buffer.append", "audio": base64.StdEncoding.EncodeToString(pcm[start:end])})
				time.Sleep(100 * time.Millisecond)
			}
			send(ws, map[string]string{"type": "input_audio_buffer.commit"})
		}
		if typ == "conversation.item.input_audio_transcription.completed" {
			text, _ := msg["transcript"].(string)
			recognized = strings.Contains(text, "音量") && (strings.Contains(text, "三十") || strings.Contains(text, "30"))
			send(ws, map[string]string{"type": "session.finish"})
		}
		if typ == "session.finished" {
			break
		}
	}
	ws.Close()
	pcm = nil
	if !recognized {
		t.Fatal("synthetic audio command not recognized")
	}
	reports := []map[string]interface{}{}
	for _, id := range []string{"audio-real-tts", "audio-real-asr"} {
		var b hardwarebilling.Bill
		deadline := time.Now().Add(5 * time.Second)
		for {
			if e := db.First(&b, "id=?", id).Error; e != nil {
				t.Fatal(e)
			}
			if b.State == "settled" || time.Now().After(deadline) {
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
		if b.State != "settled" {
			t.Fatalf("%s state %s", id, b.State)
		}
		var u hardwarebilling.Usage
		json.Unmarshal([]byte(b.UsageJSON), &u)
		reports = append(reports, map[string]interface{}{"bill_id": id, "usage": u, "cost_cny": b.CostCNY, "sale_cny": b.SaleCNY, "allocations": json.RawMessage(b.Allocations), "margin": "0.70"})
	}
	var old int64
	db.Model(&model.BailianBill{}).Count(&old)
	if old != 0 {
		t.Fatal("old ledger also charged")
	}
	if path := os.Getenv("HW_AUDIO_REPORT"); path != "" {
		raw, _ := json.Marshal(map[string]interface{}{"cases": reports, "production_changed": false, "real_authentication": true})
		if e := os.WriteFile(path, raw, 0600); e != nil {
			t.Fatal(e)
		}
	}
}
