package bailian

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/songquanpeng/one-api/model"
)

func TestHTTPOfficialReplaceReachesFake(t *testing.T) {
	t.Setenv("BAILIAN_TEST_UPSTREAM", "1")
	fake := newStrictFake()
	up := httptest.NewServer(fake.handler())
	t.Cleanup(up.Close)
	db := openTestDB(t)
	token, _ := seedGateway(t, db, up.URL)
	gw := startGateway(t, db)
	body := `{"model":"qwen-audio-3.0-tts-plus","voice":"longanlingxi","text":"啊","format":"wav","hot_fix":{"replace":[{"啊":"你好世界"}]}}`
	req, _ := http.NewRequest("POST", gw+"/bailian/v1/synthesis", strings.NewReader(body))
	req.Header = testAuth(token)
	req.Header.Set("Idempotency-Key", "official-replace")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("synth %s", raw)
	}
	fake.mu.Lock()
	got := string(fake.lastSynth)
	n := fake.synthN
	fake.mu.Unlock()
	if n != 1 {
		t.Fatalf("synthN=%d", n)
	}
	if !strings.Contains(got, `"replace"`) || !strings.Contains(got, `"你好世界"`) {
		t.Fatalf("official replace missing: %s", got)
	}
	if strings.Contains(got, `"hot_fix":{"啊"`) {
		t.Fatalf("simplified leaked: %s", got)
	}
}

func TestHTTPOfficialPronunciationAndBoth(t *testing.T) {
	t.Setenv("BAILIAN_TEST_UPSTREAM", "1")
	fake := newStrictFake()
	up := httptest.NewServer(fake.handler())
	t.Cleanup(up.Close)
	db := openTestDB(t)
	token, _ := seedGateway(t, db, up.URL)
	gw := startGateway(t, db)
	body := `{"model":"qwen-audio-3.0-tts-plus","voice":"longanlingxi","text":"天气","format":"wav","hot_fix":{"replace":[{"啊":"你好世界"}],"pronunciation":[{"天气":"tian1 qi4"}]}}`
	req, _ := http.NewRequest("POST", gw+"/bailian/v1/synthesis", strings.NewReader(body))
	req.Header = testAuth(token)
	req.Header.Set("Idempotency-Key", "official-both")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("%s", raw)
	}
	fake.mu.Lock()
	got := string(fake.lastSynth)
	fake.mu.Unlock()
	if !strings.Contains(got, `"pronunciation"`) || !strings.Contains(got, `"replace"`) {
		t.Fatalf("%s", got)
	}
}

func TestHTTPSimplifiedConvertedBeforeFake(t *testing.T) {
	t.Setenv("BAILIAN_TEST_UPSTREAM", "1")
	fake := newStrictFake()
	up := httptest.NewServer(fake.handler())
	t.Cleanup(up.Close)
	db := openTestDB(t)
	token, _ := seedGateway(t, db, up.URL)
	gw := startGateway(t, db)
	body := `{"model":"qwen-audio-3.0-tts-plus","voice":"longanlingxi","text":"啊","format":"wav","hot_fix":{"啊":"你好世界"}}`
	req, _ := http.NewRequest("POST", gw+"/bailian/v1/synthesis", strings.NewReader(body))
	req.Header = testAuth(token)
	req.Header.Set("Idempotency-Key", "simplified-converted")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("%s", raw)
	}
	fake.mu.Lock()
	got := string(fake.lastSynth)
	fake.mu.Unlock()
	if unofficialHotFixReason([]byte(extractHotFix(got))) != "" {
		t.Fatalf("fake saw unofficial %s", got)
	}
	if !strings.Contains(got, `"replace"`) {
		t.Fatalf("converted replace missing %s", got)
	}
}

func extractHotFix(synthBody string) string {
	var env map[string]interface{}
	_ = json.Unmarshal([]byte(synthBody), &env)
	input, _ := env["input"].(map[string]interface{})
	if input == nil {
		return ""
	}
	raw, _ := json.Marshal(input["hot_fix"])
	return string(raw)
}

func TestFakeRejectsUnofficialHotFixDirectly(t *testing.T) {
	fake := newStrictFake()
	up := httptest.NewServer(fake.handler())
	t.Cleanup(up.Close)
	body := `{"model":"qwen-audio-3.0-tts-plus","input":{"text":"啊","voice":"longanlingxi","format":"wav","hot_fix":{"啊":"你好世界"}}}`
	resp, err := http.Post(up.URL+"/api/v1/services/audio/tts/SpeechSynthesizer", "application/json", strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode == 200 {
		t.Fatalf("unofficial accepted %s", raw)
	}
	fake.mu.Lock()
	n := fake.synthN
	rej := fake.rejected
	fake.mu.Unlock()
	if n != 0 || rej == 0 {
		t.Fatalf("synthN=%d rejected=%d", n, rej)
	}
}

func TestHTTPHundredHitsReserveThenInsufficientZeroUpstream(t *testing.T) {
	t.Setenv("BAILIAN_TEST_UPSTREAM", "1")
	fake := newStrictFake()
	up := httptest.NewServer(fake.handler())
	t.Cleanup(up.Close)
	db := openTestDB(t)
	token, _ := seedGateway(t, db, up.URL)
	gw := startGateway(t, db)
	text := strings.Repeat("啊", 100)
	hf := map[string]interface{}{"replace": []map[string]string{{"啊": "你好世界"}}}
	rawFix, _ := json.Marshal(hf)
	units, err := EstimateSpeechUnits(text, false, rawFix)
	if err != nil {
		t.Fatal(err)
	}
	plain, _ := TTSCharacters(text, false)
	if units <= plain {
		t.Fatalf("100 hits must expand %d vs %d", units, plain)
	}
	bodyMap := map[string]interface{}{
		"model": TargetTTSPlus, "voice": "longanlingxi", "text": text, "format": "wav", "hot_fix": hf,
	}
	body, _ := json.Marshal(bodyMap)
	req, _ := http.NewRequest("POST", gw+"/bailian/v1/synthesis", strings.NewReader(string(body)))
	req.Header = testAuth(token)
	req.Header.Set("Idempotency-Key", "hundred-ok")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("funded 100-hit %s", raw)
	}
	fake.mu.Lock()
	okN := fake.synthN
	fake.mu.Unlock()
	if okN != 1 {
		t.Fatalf("funded synthN=%d", okN)
	}
	if err := db.Model(&model.User{}).Where("id = ?", 1).Update("quota", 1).Error; err != nil {
		t.Fatal(err)
	}
	if err := db.Model(&model.Token{}).Where("id = ?", 1).Updates(map[string]interface{}{"remain_quota": 1, "unlimited_quota": false}).Error; err != nil {
		t.Fatal(err)
	}
	req2, _ := http.NewRequest("POST", gw+"/bailian/v1/synthesis", strings.NewReader(string(body)))
	req2.Header = testAuth(token)
	req2.Header.Set("Idempotency-Key", "hundred-poor")
	resp2, err := http.DefaultClient.Do(req2)
	if err != nil {
		t.Fatal(err)
	}
	resp2.Body.Close()
	if resp2.StatusCode == 200 {
		t.Fatal("insufficient must fail")
	}
	fake.mu.Lock()
	if fake.synthN != 1 {
		t.Fatalf("poor path called upstream synthN=%d", fake.synthN)
	}
	fake.mu.Unlock()
}

func TestHTTPBitRateOpusKBPSAndRejects(t *testing.T) {
	t.Setenv("BAILIAN_TEST_UPSTREAM", "1")
	fake := newStrictFake()
	up := httptest.NewServer(fake.handler())
	t.Cleanup(up.Close)
	db := openTestDB(t)
	token, _ := seedGateway(t, db, up.URL)
	gw := startGateway(t, db)
	post := func(idem, body string) *http.Response {
		req, _ := http.NewRequest("POST", gw+"/bailian/v1/synthesis", strings.NewReader(body))
		req.Header = testAuth(token)
		req.Header.Set("Idempotency-Key", idem)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		return resp
	}
	ok := post("br-ok", `{"model":"qwen-audio-3.0-tts-plus","voice":"longanlingxi","text":"你好","format":"opus","bit_rate":32}`)
	raw, _ := io.ReadAll(ok.Body)
	ok.Body.Close()
	if ok.StatusCode != 200 {
		t.Fatalf("opus 32 %s", raw)
	}
	fake.mu.Lock()
	got := string(fake.lastSynth)
	n := fake.synthN
	fake.mu.Unlock()
	if n != 1 || !strings.Contains(got, `"bit_rate":32`) {
		t.Fatalf("bit_rate not forwarded n=%d %s", n, got)
	}
	lo := post("br-lo", `{"model":"qwen-audio-3.0-tts-plus","voice":"longanlingxi","text":"你好","format":"opus","bit_rate":5}`)
	lo.Body.Close()
	if lo.StatusCode == 200 {
		t.Fatal("5 kbps must fail")
	}
	hi := post("br-bps", `{"model":"qwen-audio-3.0-tts-plus","voice":"longanlingxi","text":"你好","format":"opus","bit_rate":128000}`)
	hi.Body.Close()
	if hi.StatusCode == 200 {
		t.Fatal("128000 must fail")
	}
	mp3 := post("br-mp3", `{"model":"qwen-audio-3.0-tts-plus","voice":"longanlingxi","text":"你好","format":"mp3","bit_rate":32}`)
	mp3.Body.Close()
	if mp3.StatusCode == 200 {
		t.Fatal("mp3 bit_rate must fail")
	}
	fake.mu.Lock()
	if fake.synthN != 1 {
		t.Fatalf("rejected bit_rate called upstream %d", fake.synthN)
	}
	fake.mu.Unlock()
}

func TestWSOfficialHotFixAndBitRateContract(t *testing.T) {
	t.Setenv("BAILIAN_TEST_UPSTREAM", "1")
	fake := newStrictFake()
	up := httptest.NewServer(fake.handler())
	t.Cleanup(up.Close)
	db := openTestDB(t)
	token, _ := seedGateway(t, db, up.URL)
	gw := startGateway(t, db)
	wsURL := "ws" + strings.TrimPrefix(gw, "http") + "/bailian/api-ws/v1/inference?model=qwen-audio-3.0-tts-plus"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, http.Header{"Authorization": {"Bearer sk-" + token}})
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	taskID := uuid.NewString()
	run, _ := json.Marshal(map[string]interface{}{
		"header": map[string]string{"action": "run-task", "task_id": taskID, "streaming": "duplex"},
		"payload": map[string]interface{}{
			"task_group": "audio", "task": "tts", "function": "SpeechSynthesizer",
			"model": "qwen-audio-3.0-tts-plus",
			"parameters": map[string]interface{}{
				"text_type": "PlainText", "voice": "longanlingxi", "format": "opus", "sample_rate": 16000,
				"hot_fix": map[string]interface{}{
					"replace":       []map[string]string{{"啊": "你好世界"}},
					"pronunciation": []map[string]string{{"天气": "tian1 qi4"}},
				},
				"bit_rate": 64,
			},
			"input": map[string]interface{}{},
		},
	})
	if err = conn.WriteMessage(1, run); err != nil {
		t.Fatal(err)
	}
	_, started, err := conn.ReadMessage()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(started), "task-started") {
		t.Fatalf("started: %s", started)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		fake.mu.Lock()
		got := fake.lastRun
		fake.mu.Unlock()
		if got != nil {
			payload, _ := json.Marshal(got["payload"])
			text := string(payload)
			if !strings.Contains(text, `"replace"`) || !strings.Contains(text, `"pronunciation"`) || !strings.Contains(text, `"bit_rate":64`) {
				t.Fatalf("ws upstream %s", text)
			}
			if unofficialHotFixFromWS(got) != "" {
				t.Fatalf("unofficial ws hotfix %s", text)
			}
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("upstream did not receive run-task")
}

func TestWSRejectsMP3BitRateBeforeUpstream(t *testing.T) {
	t.Setenv("BAILIAN_TEST_UPSTREAM", "1")
	fake := newStrictFake()
	up := httptest.NewServer(fake.handler())
	t.Cleanup(up.Close)
	db := openTestDB(t)
	token, _ := seedGateway(t, db, up.URL)
	gw := startGateway(t, db)
	wsURL := "ws" + strings.TrimPrefix(gw, "http") + "/bailian/api-ws/v1/inference?model=qwen-audio-3.0-tts-plus"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, http.Header{"Authorization": {"Bearer sk-" + token}})
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	taskID := uuid.NewString()
	run, _ := json.Marshal(map[string]interface{}{
		"header": map[string]string{"action": "run-task", "task_id": taskID, "streaming": "duplex"},
		"payload": map[string]interface{}{
			"task_group": "audio", "task": "tts", "function": "SpeechSynthesizer",
			"model": "qwen-audio-3.0-tts-plus",
			"parameters": map[string]interface{}{
				"text_type": "PlainText", "voice": "longanlingxi", "format": "mp3", "bit_rate": 32,
			},
			"input": map[string]interface{}{},
		},
	})
	_ = conn.WriteMessage(1, run)
	_, msg, err := conn.ReadMessage()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(msg), "task-started") {
		t.Fatalf("mp3 bit_rate started: %s", msg)
	}
	time.Sleep(50 * time.Millisecond)
	fake.mu.Lock()
	n := fake.wsN
	fake.mu.Unlock()
	if n != 0 {
		t.Fatalf("gateway dialed upstream wsN=%d", n)
	}
}

func TestConfigureTaskRejectsIllegalHotFixAndBitRate(t *testing.T) {
	p := map[string]interface{}{
		"text_type": "PlainText", "voice": "longanlingxi", "format": "wav",
		"hot_fix": map[string]interface{}{"replace": []int{1}},
	}
	if _, err := ConfigureTask(runTask(p), ttsCap(), nil); err == nil {
		t.Fatal("illegal nested hotfix")
	}
	p2 := map[string]interface{}{"text_type": "PlainText", "voice": "longanlingxi", "format": "opus", "bit_rate": 128000}
	if _, err := ConfigureTask(runTask(p2), ttsCap(), nil); err == nil {
		t.Fatal("128000 kbps-as-bps")
	}
	p3 := map[string]interface{}{"text_type": "PlainText", "voice": "longanlingxi", "format": "opus", "bit_rate": 6}
	if _, err := ConfigureTask(runTask(p3), ttsCap(), nil); err != nil {
		t.Fatal(err)
	}
}
