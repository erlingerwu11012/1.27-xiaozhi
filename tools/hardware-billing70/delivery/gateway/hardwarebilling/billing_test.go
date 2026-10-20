package hardwarebilling

import (
	"encoding/json"
	"fmt"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
	"testing"
)

func ptr(n int64) *int64 { return &n }
func measured(in, out, cache int64) Usage {
	return Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "ali-fixture", Input: in, Output: out, Cached: ptr(cache)}
}
func equal(t *testing.T, got Exact, want string) {
	t.Helper()
	a, e := Parse(string(got))
	if e != nil {
		t.Fatal(e)
	}
	b, e := Parse(want)
	if e != nil || a.Cmp(b) != 0 {
		t.Fatalf("got %s want %s", got, want)
	}
}

func TestQwenPriceTiersAndCache(t *testing.T) {
	for _, tc := range []struct {
		in   int64
		cost string
	}{{128000, "0.1024"}, {128001, "0.3072024"}, {256000, "0.6144"}, {256001, "1.2288048"}, {1000000, "4.8"}} {
		t.Run(fmt.Sprint(tc.in), func(t *testing.T) {
			c, e := QwenPlusBeijing(false).Cost(measured(tc.in, 0, 0))
			if e != nil {
				t.Fatal(e)
			}
			equal(t, c, tc.cost)
		})
	}
	c, e := QwenPlusBeijing(false).Cost(measured(10000, 1000, 8000))
	if e != nil {
		t.Fatal(e)
	}
	equal(t, c, "0.00488")
	u := measured(10000, 1000, 8000)
	u.Reasoning = ptr(900)
	c, e = QwenPlusBeijing(true).Cost(u)
	if e != nil {
		t.Fatal(e)
	}
	equal(t, c, "0.01088")
}
func TestRejectUntrustedUsage(t *testing.T) {
	fixtures := []Usage{measured(-1, 0, 0), measured(2, 1, 3), measured(1000001, 0, 0), {Confirmed: true, Source: "estimated", UpstreamRequestID: "x", Cached: ptr(0)}, {Confirmed: true, Source: "upstream", Cached: ptr(0)}, {Confirmed: true, Source: "upstream", UpstreamRequestID: "x"}}
	for i, u := range fixtures {
		t.Run(fmt.Sprint(i), func(t *testing.T) {
			if _, e := QwenPlusBeijing(false).Cost(u); e == nil {
				t.Fatal("accepted invalid meter")
			}
		})
	}
}
func TestMemoryAndSmallCharges(t *testing.T) {
	p, e := MemoryLite("fact_add")
	if e != nil {
		t.Fatal(e)
	}
	c, e := p.Cost(Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "evt1", Units: "1"})
	if e != nil {
		t.Fatal(e)
	}
	equal(t, c, "0.018")
	s, e := SaleCNY(c)
	if e != nil {
		t.Fatal(e)
	}
	equal(t, s, "0.06")
	for _, tc := range []struct {
		cents, points int64
		want          string
	}{{100, 100, "6"}, {2900, 50000, "3000/29"}, {9900, 200000, "4000/33"}} {
		rate, e := CashRate(tc.cents, tc.points)
		if e != nil {
			t.Fatal(e)
		}
		a, e := Allocate([]Lot{{"lot", "paid", "200000", rate}}, s, "0")
		if e != nil {
			t.Fatal(e)
		}
		equal(t, a[0].Points, tc.want)
	}
	p, _ = MemoryLite("search")
	c, e = p.Cost(Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "s1", Units: "1"})
	if e != nil {
		t.Fatal(e)
	}
	s, _ = SaleCNY(c)
	a, e := Allocate([]Lot{{"l", "paid", "1", "0.01"}}, s, "0")
	if e != nil {
		t.Fatal(e)
	}
	equal(t, a[0].Points, "1/150")
}
func TestFIFOAndLegacyFraction(t *testing.T) {
	lots := []Lot{{"old", "legacy", "5", "0"}, {"new1", "paid", "1", "0.01"}, {"new2", "paid", "10000", "29/50000"}}
	a, e := Allocate(lots, "0.06", "10")
	if e != nil {
		t.Fatal(e)
	}
	if len(a) != 3 {
		t.Fatal(a)
	}
	equal(t, a[0].Points, "5")
	equal(t, a[1].Points, "1")
	equal(t, a[2].Points, "1000/29")
	// This pure calculation must never mutate a balance on insufficient funds.
	if _, e := Allocate([]Lot{{"a", "paid", "1", "0.01"}}, "0.02", "0"); e == nil {
		t.Fatal("overdraw")
	}
	if _, e := Allocate([]Lot{{"a", "paid", "1", "0.01"}, {"b", "legacy", "1", "0"}}, "1", "1"); e == nil {
		t.Fatal("invalid order")
	}
}
func TestUsageEnvelopes(t *testing.T) {
	good := []string{
		`{"id":"chat-x","usage":{"prompt_tokens":42,"completion_tokens":5,"total_tokens":47,"prompt_tokens_details":{"cached_tokens":0}}}`,
		`{"request_id":"ali-x","usage":{"input_tokens":42,"output_tokens":5,"total_tokens":47,"cached_tokens":20}}`,
		`{"request_id":"tts-x","usage":{"characters":12}}`,
		`{"request_id":"asr-x","usage":{"duration":1.25}}`,
	}
	for i, s := range good {
		t.Run(fmt.Sprint(i), func(t *testing.T) {
			u, e := ParseUsage([]byte(s), "")
			if e != nil || !u.Confirmed {
				t.Fatalf("%+v %v", u, e)
			}
		})
	}
	bad := []string{`{}`, `{"id":"x","usage":{"prompt_tokens":3,"completion_tokens":1}}`, `{"id":"x","usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":5,"cached_tokens":0}}`, `{"id":"x","usage":{"input_tokens":3.2,"output_tokens":1,"cached_tokens":0}}`}
	for _, s := range bad {
		if _, e := ParseUsage([]byte(s), ""); e == nil {
			t.Fatal(s)
		}
	}
}
func fixture(t *testing.T) Ledger {
	t.Helper()
	db, e := gorm.Open(sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	if e != nil {
		t.Fatal(e)
	}
	raw, e := db.DB()
	if e != nil {
		t.Fatal(e)
	}
	raw.SetMaxOpenConns(1)
	t.Cleanup(func() { raw.Close() })
	l := Ledger{db}
	if e := l.Migrate(); e != nil {
		t.Fatal(e)
	}
	if e := db.Create(&Wallet{UserID: 1, ProductAccount: "synthetic", State: "enabled"}).Error; e != nil {
		t.Fatal(e)
	}
	return l
}
func TestRechargeIdempotency(t *testing.T) {
	l := fixture(t)
	if e := l.Recharge(1, "order", 100, 100); e != nil {
		t.Fatal(e)
	}
	if e := l.Recharge(1, "order", 100, 100); e != nil {
		t.Fatal(e)
	}
	if e := l.Recharge(1, "order", 101, 100); e == nil {
		t.Fatal("snapshot changed")
	}
	if e := l.Recharge(2, "order", 100, 100); e == nil {
		t.Fatal("cross account")
	}
	var n int64
	l.DB.Model(&StoredLot{}).Count(&n)
	if n != 1 {
		t.Fatal(n)
	}
}
func begin(t *testing.T, l Ledger, id string) Bill {
	t.Helper()
	p, _ := MemoryLite("fact_add")
	b, e := l.Begin(1, id, hash([]byte(id)), p, "0.1", "0")
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func balance(t *testing.T, l Ledger) Exact {
	t.Helper()
	var lot StoredLot
	if e := l.DB.First(&lot, "user_id = ?", 1).Error; e != nil {
		t.Fatal(e)
	}
	return Exact(lot.Remaining)
}
func TestAtomicActualSettlementAndRefund(t *testing.T) {
	l := fixture(t)
	if e := l.Recharge(1, "o1", 100, 100); e != nil {
		t.Fatal(e)
	}
	begin(t, l, "r1")
	equal(t, balance(t, l), "90")
	u := Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "evt1", Units: "1"}
	b, e := l.Settle(1, "r1", u, "0")
	if e != nil || b.State != "settled" {
		t.Fatal(b, e)
	}
	equal(t, balance(t, l), "94")
	equal(t, Exact(b.CostCNY), "0.018")
	if _, e := l.Settle(1, "r1", u, "0"); e != nil {
		t.Fatal(e)
	}
	equal(t, balance(t, l), "94")
	u.Units = "2"
	if _, e := l.Settle(1, "r1", u, "0"); e == nil {
		t.Fatal("conflicting completion")
	}
	if e := l.Refund(1, "r1", "refund1"); e != nil {
		t.Fatal(e)
	}
	equal(t, balance(t, l), "100")
	if e := l.Refund(1, "r1", "refund1"); e != nil {
		t.Fatal(e)
	}
	equal(t, balance(t, l), "100")
	if e := l.Refund(1, "r1", "refund2"); e == nil {
		t.Fatal("second refund")
	}
}
func TestMissingUsageRetainsHoldAndRecovers(t *testing.T) {
	l := fixture(t)
	l.Recharge(1, "o", 100, 100)
	begin(t, l, "r")
	b, e := l.Settle(1, "r", Usage{}, "0")
	if e != nil || b.State != "pending" {
		t.Fatal(b, e)
	}
	equal(t, balance(t, l), "90")
	if _, e := l.Settle(2, "r", Usage{}, "0"); e == nil {
		t.Fatal("cross account")
	}
	b, e = l.Settle(1, "r", Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "u", Units: "1"}, "0")
	if e != nil || b.State != "settled" {
		t.Fatal(b, e)
	}
	equal(t, balance(t, l), "94")
}
func TestRestartAndOverdrawRollback(t *testing.T) {
	l := fixture(t)
	l.Recharge(1, "o", 100, 100)
	begin(t, l, "r")
	l = Ledger{l.DB}
	u := Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "u", Units: "100"}
	b, e := l.Settle(1, "r", u, "0")
	if e != nil || b.State != "outstanding" {
		t.Fatal(b, e)
	}
	equal(t, balance(t, l), "90")
	if b.UsageHash == "" {
		t.Fatal("actual debt evidence lost")
	}
	p, _ := MemoryLite("search")
	if _, e := l.Begin(1, "blocked", hash([]byte("blocked")), p, "0", "0"); e == nil {
		t.Fatal("new charge allowed with debt")
	}
	if e := l.Refund(1, "r", "release"); e != nil {
		t.Fatal(e)
	}
	equal(t, balance(t, l), "100")
	if _, e := l.Settle(1, "r", u, "0"); e == nil {
		t.Fatal("cancelled request completed")
	}
}
func TestRechargeAllowsOutstandingSettlement(t *testing.T) {
	l := fixture(t)
	l.Recharge(1, "o", 100, 100)
	begin(t, l, "r")
	u := Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "u", Units: "100"}
	b, e := l.Settle(1, "r", u, "0")
	if e != nil || b.State != "outstanding" {
		t.Fatal(b, e)
	}
	if e := l.Recharge(1, "more", 1000, 1000); e != nil {
		t.Fatal(e)
	}
	b, e = l.Settle(1, "r", u, "0")
	if e != nil || b.State != "settled" {
		t.Fatal(b, e)
	}
	lots, e := loadLots(l.DB, 1)
	if e != nil {
		t.Fatal(e)
	}
	sum := zero()
	for _, lot := range lots {
		r, e := Parse(string(lot.Remaining))
		if e != nil {
			t.Fatal(e)
		}
		sum.Add(sum, r)
	}
	equal(t, exact(sum), "500")
}
func TestLedgerPersistsOnlyMeterAndSnapshots(t *testing.T) {
	l := fixture(t)
	l.Recharge(1, "o", 100, 100)
	b := begin(t, l, "r")
	var p Price
	if e := json.Unmarshal([]byte(b.PriceJSON), &p); e != nil || p.Model != "bailian-memory-lite" {
		t.Fatal(e)
	}
	// Repeat calls return the original frozen snapshot without an extra hold.
	p.UnitCNY = "999"
	b, e := l.Begin(1, "r", hash([]byte("r")), p, "999", "0")
	if e != nil {
		t.Fatal(e)
	}
	equal(t, balance(t, l), "90")
	if _, e := l.Begin(1, "r", hash([]byte("changed")), p, "0", "0"); e == nil {
		t.Fatal("payload collision")
	}
}
