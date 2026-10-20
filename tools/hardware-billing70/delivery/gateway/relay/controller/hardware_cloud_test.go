//go:build cloud_hardware

package controller

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/common"
	"github.com/songquanpeng/one-api/common/client"
	"github.com/songquanpeng/one-api/common/config"
	"github.com/songquanpeng/one-api/common/ctxkey"
	"github.com/songquanpeng/one-api/hardwarebilling"
	"github.com/songquanpeng/one-api/middleware"
	dbmodel "github.com/songquanpeng/one-api/model"
	"github.com/songquanpeng/one-api/relay/channeltype"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
	"image"
	"image/color"
	"image/png"
	"math/big"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Real Ali HTTP response -> candidate relay -> exact bill -> balance.
// Token authentication is the production middleware, with a synthetic isolated token.
// Upstream channel choice is isolated; service proof/ownership are real.
func TestHardwareRealAliRelayAndPaidLedger(t *testing.T) {
	key := os.Getenv("CLOUD_HW_TEST_KEY")
	if key == "" || os.Getenv("CLOUD_HW_AUTHORIZED") != "1" {
		t.Fatal("explicit real-cloud authorization required")
	}
	t.Setenv("HW_BILLING_ENABLED", "1")
	secret := strings.Repeat("s", 32)
	t.Setenv("HW_BILLING_SERVICE_KEY", secret)
	config.ApproximateTokenEnabled = true // Only reversible reservation, not final usage.
	oldRedis := common.RedisEnabled
	common.RedisEnabled = false
	defer func() { common.RedisEnabled = oldRedis }()
	oldSQLite := common.UsingSQLite
	common.UsingSQLite = true
	defer func() { common.UsingSQLite = oldSQLite }()
	client.Init()
	gin.SetMode(gin.TestMode)
	db, e := gorm.Open(sqlite.Open("file:hardware-real-relay?mode=memory&cache=shared"), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	if e != nil {
		t.Fatal(e)
	}
	original := dbmodel.DB
	dbmodel.DB = db
	defer func() { dbmodel.DB = original }()
	if e = db.AutoMigrate(&dbmodel.User{}, &dbmodel.Token{}, &dbmodel.Channel{}, &dbmodel.Ability{}); e != nil {
		t.Fatal(e)
	}
	token := strings.Repeat("k", 32)
	models := "qwen-plus,qwen3-vl-flash"
	if e = db.Create(&dbmodel.User{Id: 1, Username: "hw-isolated", Password: "synthetic", Status: dbmodel.UserStatusEnabled, Quota: 500000, Group: "hardware70"}).Error; e != nil {
		t.Fatal(e)
	}
	if e = db.Create(&dbmodel.Token{Id: 1, UserId: 1, Key: token, Status: dbmodel.TokenStatusExhausted, ExpiredTime: -1, RemainQuota: 0, Models: &models}).Error; e != nil {
		t.Fatal(e)
	}
	l := hardwarebilling.Ledger{DB: db}
	if e = l.Migrate(); e != nil {
		t.Fatal(e)
	}
	if e = l.Bootstrap(1, "99017001", 0); e != nil {
		t.Fatal(e)
	}
	if e = l.Recharge(1, "synthetic-cloud-recharge", 1000, 1000); e != nil {
		t.Fatal(e)
	}
	base := "https://dashscope.aliyuncs.com/compatible-mode/v1"
	nativeBase := "https://dashscope.aliyuncs.com"
	for _, ch := range []dbmodel.Channel{
		{Id: 1, Name: "isolated-hardware-main", Type: channeltype.OpenAICompatible, Status: dbmodel.ChannelStatusEnabled, Key: key, Models: "qwen-plus", Group: "hardware70", BaseURL: &base},
		{Id: 2, Name: "isolated-hardware-vision", Type: channeltype.OpenAICompatible, Status: dbmodel.ChannelStatusEnabled, Key: os.Getenv("CLOUD_HW_VISION_KEY"), Models: "qwen3-vl-flash", Group: "hardware70", BaseURL: &base},
		{Id: 3, Name: "isolated-hardware-native", Type: channeltype.Ali, Status: dbmodel.ChannelStatusEnabled, Key: key, Models: "qwen-plus", Group: "native-test-only", BaseURL: &nativeBase},
	} {
		if e := ch.Insert(); e != nil {
			t.Fatal(e)
		}
	}
	oldCache := config.MemoryCacheEnabled
	config.MemoryCacheEnabled = false
	defer func() { config.MemoryCacheEnabled = oldCache }()
	router := gin.New()
	router.POST("/v1/chat/completions", middleware.TokenAuth(), func(c *gin.Context) {
		if strings.HasPrefix(c.GetHeader("X-HW-Request-ID"), "real-native") {
			c.Set(ctxkey.SpecificChannelId, "3")
		}
	}, middleware.Distribute(), func(c *gin.Context) {
		if err := RelayTextHelper(c); err != nil {
			c.JSON(err.StatusCode, gin.H{"error": err.Code})
		}
	})
	reports := []map[string]interface{}{}
	for _, tc := range []struct{ operation, question string }{{"native", "只说结果：一加一等于几？"}, {"native-stream", "只说结果：一加一等于几？"}, {"stream", "只说结果：一加一等于几？"}, {"llm", "只说结果：一加一等于几？"}, {"summary", "概括虚构原文：用户喜欢绿茶，周五买茶；助手答应提醒。不新增事实。"}, {"habit", "根据合成材料只返回JSON对象，键为habit和repeat_days：周一至周五每天七点读书，repeat_days=62。"}, {"vision", "这张合成图片是什么颜色？只说颜色。"}} {
		payload := map[string]interface{}{"model": "qwen-plus", "messages": []map[string]string{{"role": "user", "content": tc.question}}, "max_tokens": 120, "temperature": 0, "enable_thinking": false}
		if tc.operation == "vision" {
			if os.Getenv("CLOUD_HW_VISION_KEY") == "" {
				t.Fatal("explicit hardware vision test credential required")
			}
			red := image.NewRGBA(image.Rect(0, 0, 128, 128))
			for y := 0; y < 128; y++ {
				for x := 0; x < 128; x++ {
					red.Set(x, y, color.RGBA{255, 0, 0, 255})
				}
			}
			var buffer bytes.Buffer
			png.Encode(&buffer, red)
			payload["model"] = "qwen3-vl-flash"
			payload["messages"] = []map[string]interface{}{{"role": "user", "content": []map[string]interface{}{{"type": "text", "text": tc.question}, {"type": "image_url", "image_url": map[string]string{"url": "data:image/png;base64," + base64.StdEncoding.EncodeToString(buffer.Bytes())}}}}}
		}
		streaming := strings.Contains(tc.operation, "stream")
		if streaming {
			payload["stream"] = true
			payload["stream_options"] = map[string]bool{"include_usage": true}
		}
		raw, _ := json.Marshal(payload)
		id := "real-" + tc.operation
		operation := tc.operation
		if streaming || tc.operation == "native" {
			operation = "llm"
		}
		proof := hardwarebilling.ServiceProof{Timestamp: strconv.FormatInt(time.Now().Unix(), 10), RequestID: id, ProductAccount: "99017001", Operation: operation}
		sig, e := hardwarebilling.SignProof([]byte(secret), "POST", "/v1/chat/completions", raw, proof)
		if e != nil {
			t.Fatal(e)
		}
		call := func() *httptest.ResponseRecorder {
			request := httptest.NewRequest("POST", "/v1/chat/completions", bytes.NewReader(raw))
			request.Header.Set("Authorization", "Bearer sk-"+token)
			request.Header.Set("Content-Type", "application/json")
			request.Header.Set("X-HW-Account", proof.ProductAccount)
			request.Header.Set("X-HW-Operation", proof.Operation)
			request.Header.Set("X-HW-Request-ID", proof.RequestID)
			request.Header.Set("X-HW-Timestamp", proof.Timestamp)
			request.Header.Set("X-HW-Signature", sig)
			out := httptest.NewRecorder()
			router.ServeHTTP(out, request)
			return out
		}
		out := call()
		if out.Code != 200 {
			t.Fatalf("operation=%s status=%d", tc.operation, out.Code)
		}
		var reply struct {
			Choices []struct {
				Message struct {
					Content string `json:"content"`
				} `json:"message"`
			} `json:"choices"`
		}
		answer := ""
		if streaming {
			for _, line := range strings.Split(out.Body.String(), "\n") {
				if !strings.HasPrefix(line, "data: ") {
					continue
				}
				data := strings.TrimPrefix(line, "data: ")
				if data == "[DONE]" {
					continue
				}
				var chunk struct {
					Choices []struct {
						Delta struct {
							Content string `json:"content"`
						} `json:"delta"`
					} `json:"choices"`
				}
				if json.Unmarshal([]byte(data), &chunk) == nil {
					for _, ch := range chunk.Choices {
						answer += ch.Delta.Content
					}
				}
			}
			if answer == "" {
				t.Fatal("missing streamed answer")
			}
		} else {
			if e := json.Unmarshal(out.Body.Bytes(), &reply); e != nil || len(reply.Choices) == 0 {
				t.Fatal("missing answer")
			}
			answer = reply.Choices[0].Message.Content
		}
		if tc.operation == "llm" && !strings.Contains(answer, "2") && !strings.Contains(answer, "二") {
			t.Fatal("wrong arithmetic answer")
		}
		if tc.operation == "summary" && (!strings.Contains(answer, "绿茶") || !strings.Contains(answer, "周五")) {
			t.Fatal("summary omitted required facts")
		}
		if tc.operation == "vision" && !strings.Contains(answer, "红") {
			t.Fatal("wrong synthetic color")
		}
		if tc.operation == "habit" {
			start, end := strings.Index(answer, "{"), strings.LastIndex(answer, "}")
			if start < 0 || end < start {
				t.Fatal("habit JSON missing")
			}
			var habit map[string]interface{}
			if e := json.Unmarshal([]byte(answer[start:end+1]), &habit); e != nil || habit["repeat_days"] != float64(62) {
				t.Fatal("incorrect weekday habit")
			}
		}
		var bill hardwarebilling.Bill
		if e := db.First(&bill, "id = ?", id).Error; e != nil {
			t.Fatal(e)
		}
		if bill.State != "settled" {
			t.Fatalf("actual meter missing operation=%s state=%s", tc.operation, bill.State)
		}
		cost, _ := hardwarebilling.Parse(bill.CostCNY)
		sale, _ := hardwarebilling.Parse(bill.SaleCNY)
		margin := new(big.Rat).Quo(new(big.Rat).Sub(sale, cost), sale)
		if margin.Cmp(big.NewRat(7, 10)) != 0 {
			t.Fatal("incorrect paid margin")
		}
		before := bill.Allocations
		if retry := call(); retry.Code != 403 {
			t.Fatal("repeat accepted")
		}
		db.First(&bill, "id = ?", id)
		if bill.Allocations != before {
			t.Fatal("replay changed debit")
		}
		reports = append(reports, map[string]interface{}{"operation": tc.operation, "cost_cny": bill.CostCNY, "sale_cny": bill.SaleCNY, "allocations": json.RawMessage(bill.Allocations), "usage": json.RawMessage(bill.UsageJSON), "margin": "0.70", "duplicate_rejected": true})
	}
	raw, _ := json.Marshal(map[string]interface{}{"real_relay": true, "synthetic_token_context": false, "real_token_authentication": true, "cases": reports, "production_changed": false, "real_channel_distribution": true})
	if output := os.Getenv("CLOUD_HW_RESULT_FILE"); output != "" {
		if e := os.WriteFile(output, raw, 0600); e != nil {
			t.Fatal(e)
		}
	}
	t.Log("HARDWARE_CLOUD_REPORT " + string(raw))
}
