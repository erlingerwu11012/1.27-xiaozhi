//go:build cloud_memory

package bailian

import (
	"encoding/json"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/songquanpeng/one-api/hardwarebilling"
	"github.com/songquanpeng/one-api/model"
	"io"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Explicit opt-in only. Uses synthetic wallets and two temporary Ali persons.
func TestMemoryRealCloudLifecycle(t *testing.T) {
	upstream := os.Getenv("CLOUD_MEMORY_TEST_KEY")
	if upstream == "" || os.Getenv("CLOUD_MEMORY_TEST_AUTHORIZED") != "1" {
		t.Fatal("cloud test requires explicit credentials and authorization")
	}
	t.Setenv("BAILIAN_MEMORY_CHANNEL_ID", "2")
	t.Setenv("BAILIAN_MEMORY_BILLING", "1")
	t.Setenv("BAILIAN_MEMORY_SERVICE_SECRET", strings.Repeat("s", 32))
	t.Setenv("BAILIAN_MEMORY_RULES_VERIFIED", "1")
	t.Setenv("BAILIAN_MEMORY_DEFAULT_FACT_STRATEGY", "lite")
	t.Setenv("BAILIAN_MEMORY_STORAGE_COUNT_VERIFIED", "1")
	t.Setenv("BAILIAN_MEMORY_PORTRAIT_ENABLED", "0")
	g, db := memoryFixture(t, 100000)
	if os.Getenv("CLOUD_MEMORY_HW_LEDGER") == "1" {
		t.Setenv("HW_BILLING_ENABLED", "1")
		ledger := hardwarebilling.Ledger{DB: db}
		if e := ledger.Migrate(); e != nil {
			t.Fatal(e)
		}
		if e := ledger.Bootstrap(1, "99100001", 0); e != nil {
			t.Fatal(e)
		}
		if e := ledger.Recharge(1, "memory-cloud", 100, 100); e != nil {
			t.Fatal(e)
		}
	}
	key := "syntheticmemorycloudtesttoken0001"
	db.Model(&model.Token{}).Where("id = 1").Update("key", key)
	db.Model(&model.Channel{}).Where("id = 2").Update("key", upstream)
	gin.SetMode(gin.TestMode)
	router := gin.New()
	g.MemoryRoutes(router)
	call := func(method, path, person, idem string, body interface{}) (int, map[string]interface{}) {
		raw, _ := json.Marshal(body)
		request := httptest.NewRequest(method, memoryPrefix+path, strings.NewReader(string(raw)))
		request.Header.Set("Authorization", "Bearer sk-"+key)
		expiry := strconv.FormatInt(time.Now().Unix()+120, 10)
		request.Header.Set("X-Memory-Account", "99100001")
		request.Header.Set("X-Memory-Person", person)
		request.Header.Set("X-Memory-Generation", "0")
		request.Header.Set("X-Memory-Expires", expiry)
		request.Header.Set("X-Memory-Signature", memoryAttestation(strings.Repeat("s", 32), 1, "99100001", person, "0", expiry))
		request.Header.Set("Idempotency-Key", idem)
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		var result map[string]interface{}
		data, _ := io.ReadAll(response.Body)
		json.Unmarshal(data, &result)
		return response.Code, result
	}
	persons := []string{"test_" + strings.ReplaceAll(uuid.NewString(), "-", ""), "test_" + strings.ReplaceAll(uuid.NewString(), "-", "")}
	events := map[string]string{}
	wait := func(person, event string) bool {
		for i := 0; i < 30; i++ {
			status, result := call("GET", "/events/"+event, person, "", nil)
			if status != 200 {
				return false
			}
			states := []string{}
			if list, ok := result["events"].([]interface{}); ok {
				for _, item := range list {
					if row, ok := item.(map[string]interface{}); ok {
						states = append(states, str(row["status"]))
					}
				}
			}
			if state, ok := result["status"].(string); ok {
				states = append(states, state)
			}
			complete := len(states) > 0
			for _, state := range states {
				if state == "FAILED" || state == "UNRECORDED" {
					return false
				}
				complete = complete && state == "SUCCEEDED"
			}
			if complete {
				return true
			}
			time.Sleep(2 * time.Second)
		}
		return false
	}
	cleanup := func(person string) bool {
		if event := events[person]; event != "" && !wait(person, event) {
			return false
		}
		for page := 0; page < 10; page++ {
			status, result := call("GET", "/memory_nodes?page_num=1&page_size=100", person, "", nil)
			if status != 200 {
				return false
			}
			nodes, _ := result["memory_nodes"].([]interface{})
			if len(nodes) == 0 {
				call("POST", "/entities/retire", person, "", map[string]interface{}{})
				status, _ = call("POST", "/entities/cleanup-complete", person, "", map[string]interface{}{})
				return status == 200 && result["total"] == float64(0)
			}
			for _, item := range nodes {
				node, _ := item.(map[string]interface{})
				status, _ = call("DELETE", "/memory_nodes/"+str(node["memory_node_id"]), person, "", nil)
				if status != 200 {
					return false
				}
			}
		}
		return false
	}
	t.Cleanup(func() {
		for _, person := range persons {
			if !cleanup(person) {
				t.Errorf("temporary person cleanup unconfirmed: %s", person)
			}
		}
	})
	report := map[string]interface{}{"persons": persons, "portrait_written": false}
	preferences := []string{"我平时喜欢喝茉莉花茶，不喜欢喝咖啡。", "我平时喜欢喝拿铁咖啡，不喜欢喝茶。"}
	for i, person := range persons {
		body := map[string]interface{}{"messages": []interface{}{map[string]string{"role": "user", "content": preferences[i]}}}
		status, result := call("POST", "/add-async", person, "cloud-add-"+person, body)
		if status != 200 {
			t.Fatalf("Add failed status=%d code=%v message=%v error=%v", status, result["code"], result["message"], result["error"])
		}
		event := str(result["event_id"])
		if event == "" {
			t.Fatal("missing event")
		}
		events[person] = event
		if !wait(person, event) {
			t.Fatal("async extraction did not complete")
		}
		status, result = call("GET", "/memory_nodes?page_size=100", person, "", nil)
		if status != 200 || result["total"] == nil {
			t.Fatal("actual storage total missing")
		}
		if result["total"].(float64) < 1 {
			t.Fatal("fact extraction returned no facts")
		}
		report[person+"_total"] = result["total"]
		nodes, _ := result["memory_nodes"].([]interface{})
		if len(nodes) > 0 {
			report[person+"_project"] = nodes[0].(map[string]interface{})["project_id"]
		}
		status, result = call("POST", "/memory_nodes/search", person, "cloud-search-"+person, map[string]interface{}{"messages": []interface{}{map[string]string{"role": "user", "content": "我喜欢喝什么？"}}})
		if status != 200 {
			t.Fatal("Search failed", status, result["error"])
		}
		nodes, _ = result["memory_nodes"].([]interface{})
		if len(nodes) == 0 {
			t.Fatal("Search found no known preference")
		}
		text, _ := json.Marshal(nodes)
		if i == 0 && strings.Contains(string(text), "拿铁") || i == 1 && strings.Contains(string(text), "茉莉") {
			t.Fatal("persons crossed")
		}
		report[person+"_search_plan"] = result["plan_version"]
	}
	if !cleanup(persons[0]) {
		t.Fatal("single-person fact deletion not confirmed")
	}
	status, other := call("GET", "/memory_nodes", persons[1], "", nil)
	if status != 200 || other["total"] != report[persons[1]+"_total"] {
		t.Fatal("deleting one person affected another")
	}
	report["single_person_delete_isolated"] = true
	if err := g.collectMemoryStorage(g.Context, time.Now()); err != nil {
		t.Fatal("storage sampling failed", err)
	}
	var user model.User
	db.First(&user, 1)
	report["synthetic_wallet_used_quota"] = user.UsedQuota
	if os.Getenv("CLOUD_MEMORY_HW_LEDGER") == "1" {
		var bills []hardwarebilling.Bill
		if e := db.Find(&bills).Error; e != nil {
			t.Fatal(e)
		}
		rows := []map[string]interface{}{}
		for _, bill := range bills {
			if bill.State != "settled" {
				t.Fatalf("memory bill not settled: %s", bill.State)
			}
			var price hardwarebilling.Price
			var usage hardwarebilling.Usage
			json.Unmarshal([]byte(bill.PriceJSON), &price)
			json.Unmarshal([]byte(bill.UsageJSON), &usage)
			expected, e := hardwarebilling.SaleCNY(hardwarebilling.Exact(bill.CostCNY))
			if e != nil || string(expected) != bill.SaleCNY {
				t.Fatal("memory margin mismatch", e)
			}
			rows = append(rows, map[string]interface{}{"operation": price.Operation, "cost_cny": bill.CostCNY, "sale_cny": bill.SaleCNY, "usage": usage, "allocations": json.RawMessage(bill.Allocations), "margin": "0.70"})
		}
		if user.UsedQuota != 0 {
			t.Fatal("legacy wallet also charged")
		}
		report["billing"] = rows
		if file := os.Getenv("HW_MEMORY_REPORT"); file != "" {
			encoded, _ := json.Marshal(report)
			if e := os.WriteFile(file, encoded, 0600); e != nil {
				t.Fatal(e)
			}
		}
	}
	encoded, _ := json.Marshal(report)
	t.Log("CLOUD_REPORT " + string(encoded))
}

func str(value interface{}) string { text, _ := value.(string); return text }
