package hardwarebilling

import (
	"github.com/gin-gonic/gin"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestHTTPProofWalletIsolationReplayAndLocalCancellation(t *testing.T) {
	gin.SetMode(gin.TestMode)
	l := fixture(t)
	l.DB.Model(&Wallet{}).Where("user_id = 1").Update("product_account", "99001")
	if e := l.Recharge(1, "http-test", 100, 100); e != nil {
		t.Fatal(e)
	}
	p, _ := MemoryLite("search")
	raw := []byte(`{"query":"synthetic"}`)
	key := []byte(strings.Repeat("k", 32))
	create := func(account string, signed bool) *gin.Context {
		c, _ := gin.CreateTestContext(httptest.NewRecorder())
		c.Request = httptest.NewRequest("POST", "/v1/synthetic?limit=5", strings.NewReader(string(raw)))
		if account != "" {
			c.Request.Header.Set("X-HW-Account", account)
		}
		if signed {
			proof := ServiceProof{Timestamp: strconv.FormatInt(time.Now().Unix(), 10), RequestID: "http-once", ProductAccount: account, Operation: "search"}
			sig, e := SignProof(key, c.Request.Method, c.Request.URL.RequestURI(), raw, proof)
			if e != nil {
				t.Fatal(e)
			}
			c.Request.Header.Set("X-HW-Operation", proof.Operation)
			c.Request.Header.Set("X-HW-Request-ID", proof.RequestID)
			c.Request.Header.Set("X-HW-Timestamp", proof.Timestamp)
			c.Request.Header.Set("X-HW-Signature", sig)
		}
		return c
	}
	for _, c := range []*gin.Context{create("", false), create("99002", true), create("99001", false)} {
		if _, e := l.PrepareHTTP(c, true, key, 1, raw, p, "0.01", "0"); e == nil {
			t.Fatal("untrusted request accepted")
		}
	}
	if _, e := l.PrepareHTTP(create("99001", true), false, key, 1, raw, p, "0.01", "0"); e == nil {
		t.Fatal("disabled billing downgraded")
	}
	b, e := l.PrepareHTTP(create("99001", true), true, key, 1, raw, p, "0.01", "0")
	if e != nil {
		t.Fatal(e)
	}
	if _, e := l.PrepareHTTP(create("99001", true), true, key, 1, raw, p, "0.01", "0"); e == nil {
		t.Fatal("second upstream dispatch accepted")
	}
	if e := l.CancelBeforeDispatch(1, b.ID); e != nil {
		t.Fatal(e)
	}
	if e := l.CancelBeforeDispatch(1, b.ID); e != nil {
		t.Fatal(e)
	}
	lots, e := loadLots(l.DB, 1)
	if e != nil {
		t.Fatal(e)
	}
	equal(t, lots[0].Remaining, "100")
	// Aimi/unmigrated wallets retain their existing route only with no HW proof.
	if b, e := l.PrepareHTTP(create("", false), true, key, 777, raw, p, "0", "0"); e != nil || b != nil {
		t.Fatal("unmigrated wallet changed", e)
	}
}
