package hardwarebilling

import "testing"

func TestAudioReservationIsReversibleAndNotFinalUsage(t *testing.T) {
	l := fixture(t)
	if e := l.Recharge(1, "audio", 100, 100); e != nil {
		t.Fatal(e)
	}
	p, e := BeijingPrice("qwen3-asr-flash-realtime", "asr", false)
	if e != nil {
		t.Fatal(e)
	}
	b, e := l.Begin(1, "audio", hash([]byte("audio")), p, "0.01", "0")
	if e != nil {
		t.Fatal(e)
	}
	if e = l.ResizeReservation(1, b.ID, "0.02", "0"); e != nil {
		t.Fatal(e)
	}
	if e = l.ResizeReservation(1, b.ID, "2", "0"); e == nil {
		t.Fatal("overdraw")
	}
	var stored Bill
	l.DB.First(&stored, "id = ?", b.ID)
	if stored.CostCNY != "" || stored.UsageJSON != "" || stored.State != "reserved" {
		t.Fatal(stored)
	}
	u := Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "asr-receipt", Units: "3"}
	b, e = l.Settle(1, b.ID, u, "0")
	if e != nil {
		t.Fatal(e)
	}
	equal(t, Exact(b.SaleCNY), "0.0033")
	if e = l.ResizeReservation(1, b.ID, "0.01", "0"); e == nil {
		t.Fatal("settled hold resized")
	}
	var lot StoredLot
	l.DB.First(&lot)
	equal(t, Exact(lot.Remaining), "99.67")
}
