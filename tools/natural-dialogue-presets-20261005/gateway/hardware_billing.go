package controller

import (
	"errors"
	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/common"
	"github.com/songquanpeng/one-api/hardwarebilling"
	dbmodel "github.com/songquanpeng/one-api/model"
	billingratio "github.com/songquanpeng/one-api/relay/billing/ratio"
	"github.com/songquanpeng/one-api/relay/meta"
	relaymodel "github.com/songquanpeng/one-api/relay/model"
	"math/big"
	"net/url"
	"os"
	"strconv"
)

type hardwareTextCall struct {
	ledger hardwarebilling.Ledger
	bill   hardwarebilling.Bill
	user   int
	price  hardwarebilling.Price
}

func prepareHardwareText(c *gin.Context, m *meta.Meta, request *relaymodel.GeneralOpenAIRequest, promptTokens int) (*hardwareTextCall, error) {
	enabled := os.Getenv("HW_BILLING_ENABLED") == "1"
	if !enabled && c.GetHeader("X-HW-Account") == "" && c.GetHeader("X-HW-Signature") == "" {
		return nil, nil
	}
	raw, e := common.GetRequestBody(c)
	if e != nil {
		return nil, e
	}
	l := hardwarebilling.Ledger{DB: dbmodel.DB}
	var price hardwarebilling.Price
	hold, legacy := hardwarebilling.Exact("0"), hardwarebilling.Exact("0")
	if c.GetHeader("X-HW-Account") != "" {
		operation := c.GetHeader("X-HW-Operation")
		base, e := url.Parse(m.BaseURL)
		if e != nil || base.Scheme != "https" || base.User != nil || base.Port() != "" ||
			(base.Hostname() != "dashscope.aliyuncs.com" && base.Hostname() != "llm-ls1w1a03kewy6rw0.cn-beijing.maas.aliyuncs.com") {
			return nil, errors.New("hardware_verified_beijing_upstream_required")
		}
		thinking := false
		if request.Model == "qwen-plus" || request.Model == "qwen3.8-flash" || request.Model == "qwen3.8-max" {
			if request.EnableThinking == nil {
				return nil, errors.New("hardware_explicit_thinking_mode_required")
			}
			thinking = *request.EnableThinking
		}
		price, e = hardwarebilling.BeijingPrice(request.Model, operation, thinking)
		if e != nil {
			return nil, e
		}
		if price.Unit != "tokens" {
			return nil, errors.New("hardware_text_operation_required")
		}
		// A request estimate is a reversible hold only. Meter provenance remains upstream.
		maximum := request.MaxTokens
		if maximum <= 0 {
			maximum = 4096
		}
		zero := int64(0)
		estimated := hardwarebilling.Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "reservation-only", Input: int64(promptTokens), Output: int64(maximum), Cached: &zero}
		cost, e := price.Cost(estimated)
		if e != nil {
			return nil, e
		}
		hold, e = hardwarebilling.SaleCNY(cost)
		if e != nil {
			return nil, e
		}
		modelRate := billingratio.GetModelRatio(request.Model, m.ChannelType) * billingratio.GetGroupRatio(m.Group)
		outputRate := billingratio.GetCompletionRatio(request.Model, m.ChannelType)
		price.LegacyInputRate = hardwarebilling.Exact(strconv.FormatFloat(modelRate, 'f', -1, 64))
		price.LegacyOutputRate = hardwarebilling.Exact(strconv.FormatFloat(modelRate*outputRate, 'f', -1, 64))
		legacy, e = legacyDebit(price, int64(promptTokens), int64(maximum))
		if e != nil {
			return nil, e
		}
	}
	b, e := l.PrepareHTTP(c, enabled, []byte(os.Getenv("HW_BILLING_SERVICE_KEY")), m.UserId, raw, price, hold, legacy)
	if e != nil || b == nil {
		return nil, e
	}
	c.Header("X-HW-Bill-ID", b.ID)
	return &hardwareTextCall{l, *b, m.UserId, price}, nil
}

// Freeze the old user's model/group rates in the bill. Whole quota rounding is
// retained ONLY for legacy points. New paid fees remain exact fractions.
func legacyDebit(p hardwarebilling.Price, input, output int64) (hardwarebilling.Exact, error) {
	a, e := hardwarebilling.Parse(string(p.LegacyInputRate))
	if e != nil {
		return "", e
	}
	b, e := hardwarebilling.Parse(string(p.LegacyOutputRate))
	if e != nil {
		return "", e
	}
	total := new(big.Rat).Mul(a, new(big.Rat).SetInt64(input))
	total.Add(total, new(big.Rat).Mul(b, new(big.Rat).SetInt64(output)))
	whole := new(big.Int).Quo(total.Num(), total.Denom())
	if new(big.Int).Mod(total.Num(), total.Denom()).Sign() != 0 {
		whole.Add(whole, big.NewInt(1))
	}
	return hardwarebilling.Exact(new(big.Rat).SetFrac(whole, big.NewInt(500)).RatString()), nil
}
func (h *hardwareTextCall) settle(usage *relaymodel.Usage) error {
	actual := hardwarebilling.Usage{Source: "upstream"}
	if usage != nil && usage.ActualEvidence != nil {
		actual = *usage.ActualEvidence
	}
	legacy := hardwarebilling.Exact("0")
	if actual.Confirmed {
		var e error
		legacy, e = legacyDebit(h.price, actual.Input, actual.Output)
		if e != nil {
			return e
		}
	}
	_, e := h.ledger.Settle(h.user, h.bill.ID, actual, legacy)
	return e
}
func (h *hardwareTextCall) cancelLocal() { _ = h.ledger.CancelBeforeDispatch(h.user, h.bill.ID) }
