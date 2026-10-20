package bailian

import (
	"github.com/songquanpeng/one-api/hardwarebilling"
	"testing"
)

func TestHardwareASRUsesOfficialRootUsage(t *testing.T) {
	s := ASRState{Finishing: true}
	if _, e := s.Server([]byte(`{"type":"session.created","session":{"id":"ali-session"}}`)); e != nil {
		t.Fatal(e)
	}
	if _, e := s.Server([]byte(`{"type":"session.finished","usage":{"duration":3,"input_tokens":57,"output_tokens":22}}`)); e != nil {
		t.Fatal(e)
	}
	if !s.UsageSeen || s.ConfirmedSeconds != 3 || s.RequestID != "ali-session" {
		t.Fatal(s)
	}
	if _, e := s.Server([]byte(`{"type":"session.finished","usage":{"duration":3},"payload":{"usage":{"duration":4}}}`)); e == nil {
		t.Fatal("conflicting usage accepted")
	}
}

func TestHardwareAudioDoesNotChargePCMEstimates(t *testing.T) {
	for _, confirmed := range []bool{false, true} {
		t.Run(map[bool]string{false: "missing-meter", true: "official-meter"}[confirmed], func(t *testing.T) {
			l := hardwarebilling.Ledger{DB: openTestDB(t)}
			if e := l.Migrate(); e != nil {
				t.Fatal(e)
			}
			if e := l.Bootstrap(1, "99001", 0); e != nil {
				t.Fatal(e)
			}
			if e := l.Recharge(1, "audio", 100, 100); e != nil {
				t.Fatal(e)
			}
			p, e := hardwarebilling.BeijingPrice("qwen3-asr-flash-realtime", "asr", false)
			if e != nil {
				t.Fatal(e)
			}
			b, e := l.Begin(1, "audio", hash([]byte("audio")), p, "0.01", "0")
			if e != nil {
				t.Fatal(e)
			}
			old := Price{Version: "frozen", Region: "cn-beijing", Unit: "audio_second", CNYPerUnit: "0.00033", ModelMultiplier: "1.43", GroupMultiplier: "1", QuotaPerUSD: "500000", CNYPerUSD: "7.2"}
			h := hardwareAudioCall{l, b, 1, p, old}
			s := ASRState{Bytes: 999999, Rate: 16000, UsageSeen: confirmed, ConfirmedSeconds: 3, RequestID: "ali-session"}
			if e = h.finish(nil, &s, true); e != nil {
				t.Fatal(e)
			}
			var got hardwarebilling.Bill
			l.DB.First(&got, "id = ?", b.ID)
			if confirmed {
				if got.State != "settled" || got.CostCNY != "99/100000" || got.SaleCNY != "33/10000" {
					t.Fatal(got)
				}
			} else {
				if got.State != "pending" || got.CostCNY != "" || got.SaleCNY != "" {
					t.Fatal("estimated bytes billed", got)
				}
			}
		})
	}
}
