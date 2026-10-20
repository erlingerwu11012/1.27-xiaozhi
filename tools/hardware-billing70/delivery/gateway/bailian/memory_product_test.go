package bailian

import (
	"encoding/json"
	"errors"
	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/model"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestMemoryProductOwnershipIdempotencyAndSingleMultiplier(t *testing.T) {
	t.Setenv("BAILIAN_MEMORY_CHANNEL_ID", "2")
	t.Setenv("BAILIAN_MEMORY_BILLING", "1")
	t.Setenv("BAILIAN_MEMORY_SERVICE_SECRET", strings.Repeat("x", 32))
	t.Setenv("BAILIAN_MEMORY_RULES_VERIFIED", "1")
	t.Setenv("BAILIAN_MEMORY_DEFAULT_FACT_STRATEGY", "lite")
	t.Setenv("BAILIAN_MEMORY_STORAGE_COUNT_VERIFIED", "1")
	g, db := memoryFixture(t, 100000)
	key := "syntheticmemoryproducttoken000001"
	db.Model(&model.Token{}).Where("id = 1").Update("key", key)
	db.Create(&model.User{Id: 2, Username: "other", Status: 1, Group: "default", Quota: 100000, AccessToken: "other", AffCode: "other"})
	otherKey := "syntheticmemoryproducttoken000002"
	db.Create(&model.Token{Id: 2, UserId: 2, Key: otherKey, Status: 1, ExpiredTime: -1, RemainQuota: 100000})
	gin.SetMode(gin.TestMode)
	router := gin.New()
	g.MemoryRoutes(router)
	request := func(method, path, person, idem, body, token string, owner int) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, memoryPrefix+path, strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer sk-"+token)
		expiry := strconv.FormatInt(time.Now().Unix()+120, 10)
		req.Header.Set("X-Memory-Account", "10")
		req.Header.Set("X-Memory-Person", person)
		req.Header.Set("X-Memory-Generation", "0")
		req.Header.Set("X-Memory-Expires", expiry)
		req.Header.Set("X-Memory-Signature", memoryAttestation(strings.Repeat("x", 32), owner, "10", person, "0", expiry))
		req.Header.Set("Idempotency-Key", idem)
		out := httptest.NewRecorder()
		router.ServeHTTP(out, req)
		return out
	}
	prior := memoryClient
	t.Cleanup(func() { memoryClient = prior })
	calls := 0
	unknown := false
	memoryClient = &http.Client{Transport: memoryTestTransport(func(req *http.Request) (*http.Response, error) {
		calls++
		if unknown {
			return nil, errors.New("synthetic response loss")
		}
		raw, _ := io.ReadAll(req.Body)
		var body map[string]interface{}
		json.Unmarshal(raw, &body)
		cloud := body["user_id"]
		if text, ok := cloud.(string); ok && len(text) > 64 {
			t.Fatal("cloud user id exceeds Alibaba limit")
		}
		result := map[string]interface{}{"request_id": "synthetic-product"}
		if strings.HasSuffix(req.URL.Path, "add-async") {
			if _, found := body["plan_version"]; found {
				t.Fatal("Add version is not an API body field")
			}
			if _, found := body["project_id"]; found {
				t.Fatal("verified default project unexpectedly changed")
			}
			result["event_id"] = "owned_event"
			result["events"] = []interface{}{map[string]interface{}{"event_id": "owned_event", "user_id": cloud, "status": "PENDING"}}
		} else if strings.HasSuffix(req.URL.Path, "memory_nodes/search") {
			if body["plan_version"] != "lite" || body["top_k"] != float64(5) {
				t.Fatal("search budget/version changed")
			}
			if cloud == "foreign" {
				t.Fatal("model supplied user escaped ownership binding")
			}
			result["memory_nodes"] = []interface{}{map[string]interface{}{"memory_node_id": "owned_node", "content": "synthetic preference"}}
		}
		encoded, _ := json.Marshal(result)
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(string(encoded)))}, nil
	})}
	payload := `{"messages":[{"role":"user","content":"synthetic"}],"user_id":"foreign","plan_version":"pro","top_k":99}`
	if out := request("POST", "/memory_nodes/search", "usr_a", "search-01", payload, key, 1); out.Code != 200 {
		t.Fatal(out.Code, out.Body.String())
	}
	if out := request("POST", "/memory_nodes/search", "usr_a", "search-01", payload, key, 1); out.Code != 200 || out.Header().Get("X-Memory-Replay") != "1" {
		t.Fatal("replay failed", out.Code, out.Body.String())
	}
	if calls != 1 {
		t.Fatal("duplicate upstream search")
	}
	if out := request("POST", "/memory_nodes/search", "usr_a", "search-01", `{"messages":[]}`, key, 1); out.Code != 409 {
		t.Fatal("payload conflict accepted", out.Code)
	}
	if out := request("GET", "/memory_nodes/owned_node", "usr_b", "", "", key, 1); out.Code != 403 {
		t.Fatal("cross-person read accepted", out.Code)
	}
	if out := request("GET", "/memory_nodes/owned_node", "usr_a", "", "", otherKey, 1); out.Code != 403 {
		t.Fatal("cross-wallet attestation accepted", out.Code)
	}
	if out := request("POST", "/add-async", "usr_a", "fact-001", `{"messages":[{"role":"user","content":"synthetic fact"}]}`, key, 1); out.Code != 200 {
		t.Fatal(out.Code, out.Body.String())
	}
	if calls != 2 {
		t.Fatal("unexpected call count", calls)
	}
	var user model.User
	db.First(&user, 1)
	// Search + fact = (0.00002 + 0.018) * 1.43 * 500000/7 = 1840.614285 quota.
	if user.UsedQuota != 1840 || user.Quota != 100000-1840 {
		t.Fatal("multiplier or rounding incorrect", user.UsedQuota, user.Quota)
	}
	var other model.User
	db.First(&other, 2)
	if other.Quota != 100000 {
		t.Fatal("other account charged")
	}
	unknown = true
	if out := request("POST", "/memory_nodes/search", "usr_a", "lost-001", payload, key, 1); out.Code != 502 {
		t.Fatal("unknown result not held", out.Code)
	}
	if out := request("POST", "/memory_nodes/search", "usr_a", "lost-001", payload, key, 1); out.Code != 409 {
		t.Fatal("unknown result repeated", out.Code)
	}
	if calls != 3 {
		t.Fatal("blind resubmission after response loss")
	}
	var reviews int64
	db.Model(&MemoryRequest{}).Where("state = ?", "review").Count(&reviews)
	if reviews != 1 {
		t.Fatal("missing durable review")
	}
}

func TestMemoryAccountRateLimitsResetAndUseSeparateBudgets(t *testing.T) {
	g, _ := memoryFixture(t, 0)
	now := time.Unix(1800000000, 0)
	for i := 0; i < 120; i++ {
		if !g.memoryRateAllow("add-async", now) {
			t.Fatal("early Add limit")
		}
	}
	if g.memoryRateAllow("add-async", now) {
		t.Fatal("Add limit not enforced")
	}
	for i := 0; i < 300; i++ {
		if !g.memoryRateAllow("memory_nodes/search", now) {
			t.Fatal("early Search limit")
		}
	}
	if g.memoryRateAllow("memory_nodes/search", now) {
		t.Fatal("Search limit not enforced")
	}
	if !g.memoryRateAllow("memory_nodes", now) {
		t.Fatal("maintenance blocked by Search cap")
	}
	if !g.memoryRateAllow("add-async", now.Add(time.Minute)) {
		t.Fatal("minute budget did not reset")
	}
}
