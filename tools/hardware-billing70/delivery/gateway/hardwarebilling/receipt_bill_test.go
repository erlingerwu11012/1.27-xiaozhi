package hardwarebilling

import (
	"encoding/json"
	"fmt"
	"math/big"
	"testing"
)

// Replays confirmed real test meters into an isolated ledger. This proves the
// settlement contract; it does not pretend the audio gateway is already wired.
func TestConfirmedAudioAndMemoryBillsAcrossPackages(t *testing.T) {
	cases := []struct{ model, op, raw, cost string }{
		{"qwen3-asr-flash-realtime", "asr", `{"request_id":"synthetic-asr","usage":{"duration":3,"input_tokens":57,"output_tokens":22}}`, "0.00099"},
		{"qwen-audio-3.0-tts-plus", "tts", `{"request_id":"synthetic-tts","usage":{"characters":32}}`, "0.00448"},
		{"bailian-memory-lite", "fact_add", "", "0.018"},
		{"bailian-memory-lite", "search", "", "0.00002"},
		{"bailian-memory-lite", "storage_item_hour", "", "0.0000004"},
	}
	for _, pkg := range []struct{ cents, points int64 }{{100, 100}, {2900, 50000}, {9900, 200000}} {
		t.Run(fmt.Sprintf("package-%d", pkg.cents), func(t *testing.T) {
			l := fixture(t)
			if e := l.Recharge(1, "package", pkg.cents, pkg.points); e != nil {
				t.Fatal(e)
			}
			totalCost, totalSale, totalPoints := zero(), zero(), zero()
			for i, tc := range cases {
				p, e := BeijingPrice(tc.model, tc.op, false)
				if e != nil {
					t.Fatal(e)
				}
				u := Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "synthetic-memory", Units: "1"}
				if tc.raw != "" {
					u, e = ParseUsage([]byte(tc.raw), "")
					if e != nil {
						t.Fatal(e)
					}
				}
				if tc.op == "storage_item_hour" {
					u.Units = "2"
				}
				id := fmt.Sprintf("receipt-%d", i)
				if _, e = l.Begin(1, id, hash([]byte(id)), p, "0.1", "0"); e != nil {
					t.Fatal(e)
				}
				b, e := l.Settle(1, id, u, "0")
				if e != nil || b.State != "settled" {
					t.Fatalf("%+v %v", b, e)
				}
				equal(t, Exact(b.CostCNY), tc.cost)
				c, _ := Parse(b.CostCNY)
				s, _ := Parse(b.SaleCNY)
				// Exact margin and immutable retry evidence; no minimum-point rounding.
				margin := new(big.Rat).Sub(s, c)
				margin.Quo(margin, s)
				equal(t, exact(margin), "0.7")
				before := b.Allocations
				b, e = l.Settle(1, id, u, "0")
				if e != nil || before != b.Allocations {
					t.Fatal("duplicate settlement changed bill", e)
				}
				var allocations []Allocation
				if e = json.Unmarshal([]byte(b.Allocations), &allocations); e != nil {
					t.Fatal(e)
				}
				for _, a := range allocations {
					n, _ := Parse(string(a.Points))
					totalPoints.Add(totalPoints, n)
				}
				totalCost.Add(totalCost, c)
				totalSale.Add(totalSale, s)
			}
			equal(t, exact(totalCost), "0.0234904")
			rate, e := CashRate(pkg.cents, pkg.points)
			if e != nil {
				t.Fatal(e)
			}
			r, _ := Parse(string(rate))
			equal(t, exact(new(big.Rat).Mul(totalPoints, r)), string(exact(totalSale)))
			var lots []StoredLot
			l.DB.Find(&lots)
			if len(lots) != 1 {
				t.Fatal(lots)
			}
			remaining, _ := Parse(lots[0].Remaining)
			remaining.Add(remaining, totalPoints)
			equal(t, exact(remaining), fmt.Sprint(pkg.points))
		})
	}
}
