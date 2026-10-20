package bailian

import (
	"errors"
	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/hardwarebilling"
	"math/big"
	"os"
	"strconv"
)

type hardwareAudioCall struct {
	ledger hardwarebilling.Ledger
	bill   hardwarebilling.Bill
	user   int
	price  hardwarebilling.Price
	legacy Price
}

func (g *Gateway) prepareHardwareAudio(c *gin.Context, p Principal, cap Capability, old Price) (*hardwareAudioCall, error) {
	enabled := os.Getenv("HW_BILLING_ENABLED") == "1"
	if !enabled && c.GetHeader("X-HW-Account") == "" && c.GetHeader("X-HW-Signature") == "" {
		return nil, nil
	}
	l := hardwarebilling.Ledger{DB: g.DB}
	var price hardwarebilling.Price
	sale, legacy := hardwarebilling.Exact("0"), hardwarebilling.Exact("0")
	if c.GetHeader("X-HW-Account") != "" {
		// The signed GET must name the model; initial WebSocket frames cannot change it.
		if c.Query("model") != cap.Model {
			return nil, errors.New("hardware_audio_model_binding_required")
		}
		operation := "tts"
		if cap.Protocol == "asr_realtime" {
			operation = "asr"
		}
		var e error
		price, e = hardwarebilling.BeijingPrice(cap.Model, operation, false)
		if e != nil {
			return nil, e
		}
		cost, e := price.Cost(hardwarebilling.Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "reservation-only", Units: "1"})
		if e != nil {
			return nil, e
		}
		sale, e = hardwarebilling.SaleCNY(cost)
		if e != nil {
			return nil, e
		}
		n, e := old.Quota(1, 1)
		if e != nil {
			return nil, e
		}
		legacy = hardwarebilling.Exact(new(big.Rat).SetFrac(big.NewInt(n), big.NewInt(500)).RatString())
	}
	b, e := l.PrepareHTTP(c, enabled, []byte(os.Getenv("HW_BILLING_SERVICE_KEY")), p.User.Id, nil, price, sale, legacy)
	if e != nil || b == nil {
		return nil, e
	}
	return &hardwareAudioCall{l, *b, p.User.Id, price, old}, nil
}

func (h *hardwareAudioCall) grow(n, d int64) error {
	if n < 0 || d <= 0 {
		return errors.New("invalid_audio_hold")
	}
	units := hardwarebilling.Exact(new(big.Rat).SetFrac(big.NewInt(n), big.NewInt(d)).RatString())
	cost, e := h.price.Cost(hardwarebilling.Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "reservation-only", Units: units})
	if e != nil {
		return e
	}
	sale, e := hardwarebilling.SaleCNY(cost)
	if e != nil {
		return e
	}
	q, e := h.legacy.Quota(n, d)
	if e != nil {
		return e
	}
	return h.ledger.ResizeReservation(h.user, h.bill.ID, sale, hardwarebilling.Exact(new(big.Rat).SetFrac(big.NewInt(q), big.NewInt(500)).RatString()))
}

func (h *hardwareAudioCall) finish(native *NativeState, asr *ASRState, dispatched bool) error {
	if !dispatched {
		return h.ledger.CancelBeforeDispatch(h.user, h.bill.ID)
	}
	u := hardwarebilling.Usage{Source: "upstream", UpstreamRequestID: ""}
	var units int64
	if native != nil && native.UsageSeen {
		units = native.ConfirmedUnits
		u.Confirmed = native.TaskID != ""
		u.UpstreamRequestID = native.TaskID
	}
	if asr != nil && asr.UsageSeen {
		units = asr.ConfirmedSeconds
		u.Confirmed = asr.RequestID != ""
		u.UpstreamRequestID = asr.RequestID
	}
	legacy := hardwarebilling.Exact("0")
	if u.Confirmed {
		u.Units = hardwarebilling.Exact(strconv.FormatInt(units, 10))
		q, e := h.legacy.Quota(units, 1)
		if e != nil {
			return e
		}
		legacy = hardwarebilling.Exact(new(big.Rat).SetFrac(big.NewInt(q), big.NewInt(500)).RatString())
	}
	// No PCM-byte fallback. Interrupted/finished without official usage is pending.
	_, e := h.ledger.Settle(h.user, h.bill.ID, u, legacy)
	return e
}
