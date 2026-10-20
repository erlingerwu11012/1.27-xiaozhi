package hardwarebilling

import (
	"errors"
	"math/big"
)

// Usage is evidence from a response, never a locally counted prompt. Nil cached
// means unknown, distinct from a confirmed zero; unknown costs stay pending.
type Usage struct {
	Confirmed         bool   `json:"confirmed"`
	Source            string `json:"source"`
	UpstreamRequestID string `json:"upstream_request_id"`
	Input             int64  `json:"input_tokens"`
	Output            int64  `json:"output_tokens"`
	Cached            *int64 `json:"cached_tokens"`
	Reasoning         *int64 `json:"reasoning_tokens,omitempty"`
	Units             Exact  `json:"units,omitempty"`
}
type Tier struct {
	MaxInput int64 `json:"max_input"`
	Input    Exact `json:"input_per_million"`
	Output   Exact `json:"output_per_million"`
	Cached   Exact `json:"cached_per_million"`
}
type Price struct {
	LegacyInputRate  Exact  `json:"legacy_input_rate,omitempty"`
	LegacyOutputRate Exact  `json:"legacy_output_rate,omitempty"`
	Version          string `json:"version"`
	Region           string `json:"region"`
	Model            string `json:"model"`
	Operation        string `json:"operation"`
	Mode             string `json:"mode"`
	SourceURL        string `json:"source_url"`
	Unit             string `json:"unit"`
	UnitCNY          Exact  `json:"unit_cny,omitempty"`
	Tiers            []Tier `json:"tiers,omitempty"`
}

func (p Price) Cost(u Usage) (Exact, error) {
	if !u.Confirmed || u.Source != "upstream" || u.UpstreamRequestID == "" {
		return "", errors.New("usage_pending")
	}
	if p.Version == "" || p.Region == "" || p.SourceURL == "" || p.Model == "" || p.Operation == "" {
		return "", errors.New("price_unverified")
	}
	if p.Unit != "tokens" {
		n, e := Parse(string(u.Units))
		if e != nil {
			return "", e
		}
		unit, e := Parse(string(p.UnitCNY))
		if e != nil {
			return "", e
		}
		return exact(n.Mul(n, unit)), nil
	}
	if u.Input < 0 || u.Output < 0 || u.Cached == nil {
		return "", errors.New("usage_pending")
	}
	if *u.Cached < 0 || *u.Cached > u.Input || (u.Reasoning != nil && (*u.Reasoning < 0 || *u.Reasoning > u.Output)) {
		return "", errors.New("invalid_usage")
	}
	for _, t := range p.Tiers {
		if u.Input <= t.MaxInput {
			rates := []Exact{t.Input, t.Output, t.Cached}
			units := []int64{u.Input - *u.Cached, u.Output, *u.Cached}
			total := zero()
			for i, rate := range rates {
				r, e := Parse(string(rate))
				if e != nil {
					return "", e
				}
				total.Add(total, new(big.Rat).Mul(r, integer(units[i])))
			}
			// Reasoning is already included in output tokens: never charge twice.
			return exact(total.Quo(total, integer(1000000))), nil
		}
	}
	return "", errors.New("input_outside_verified_tiers")
}

func QwenPlusBeijing(thinking bool) Price {
	mode := "non_thinking"
	outs := []Exact{"2", "20", "48"}
	if thinking {
		mode = "thinking"
		outs = []Exact{"8", "24", "64"}
	}
	return Price{Version: "aliyun-beijing-20261001-v1", Region: "cn-beijing", Model: "qwen-plus", Operation: "llm", Mode: mode, SourceURL: "https://help.aliyun.com/zh/model-studio/qwen-plus", Unit: "tokens", Tiers: []Tier{
		{128000, "0.8", outs[0], "0.16"}, {256000, "2.4", outs[1], "0.48"}, {1000000, "4.8", outs[2], "0.96"},
	}}
}

func MemoryLite(operation string) (Price, error) {
	rates := map[string]Exact{"fact_add": "0.018", "portrait_add": "0.025", "search": "0.00002", "storage_item_hour": "0.0000002"}
	rate, ok := rates[operation]
	if !ok {
		return Price{}, errors.New("unverified_memory_operation")
	}
	return Price{Version: "aliyun-memory-20261001-v1", Region: "cn-beijing", Model: "bailian-memory-lite", Operation: operation, Mode: "lite", SourceURL: "https://help.aliyun.com/zh/model-studio/memory/billing", Unit: "official_units", UnitCNY: rate}, nil
}

func MemoryPrice(operation, strategy string) (Price, error) {
	p, e := MemoryLite(operation)
	if e != nil {
		return p, e
	}
	if strategy == "lite" {
		return p, nil
	}
	if strategy != "pro" {
		return Price{}, errors.New("unverified_memory_strategy")
	}
	rates := map[string]Exact{"fact_add": "0.03", "portrait_add": "0.03", "search": "0.001", "storage_item_hour": "0.0000002"}
	p.Model = "bailian-memory-pro"
	p.Mode = "pro"
	p.UnitCNY = rates[operation]
	return p, nil
}

// Only verified Beijing routes are offered to the hardware billing path.
// A model alias or another region cannot silently inherit these prices.
func BeijingPrice(model, operation string, thinking bool) (Price, error) {
	if model == "qwen3.7-plus" && (operation == "llm" || operation == "summary" || operation == "habit") {
		mode := "non_thinking"
		maximum := int64(991808)
		if thinking {
			mode = "thinking"
			maximum = 983616
		}
		return Price{Version: "aliyun-beijing-20261007-qwen37", Region: "cn-beijing", Model: model, Operation: operation, Mode: mode, SourceURL: "https://help.aliyun.com/zh/model-studio/qwen3-7-plus", Unit: "tokens", Tiers: []Tier{{256000, "2", "8", "0.4"}, {maximum, "6", "24", "1.2"}}}, nil
	}

	if (model == "qwen3.8-flash" || model == "qwen3.8-max") && (operation == "llm" || operation == "summary" || operation == "habit") {
		// Verified Beijing aliases only. Keep thinking and cached token provenance explicit.
		mode := "non_thinking"
		if thinking {
			mode = "thinking"
		}
		tier := Tier{991808, "0.8", "2.7", "0.1"}
		source := "https://help.aliyun.com/zh/model-studio/qwen3-8-flash"
		if model == "qwen3.8-max" {
			tier = Tier{991808, "12", "36", "1.5"}
			source = "https://help.aliyun.com/zh/model-studio/qwen3-8-max"
		}
		if thinking {
			tier.MaxInput = 983616
		}
		return Price{Version: "aliyun-beijing-20261005", Region: "cn-beijing", Model: model, Operation: operation, Mode: mode, SourceURL: source, Unit: "tokens", Tiers: []Tier{tier}}, nil
	}
	if model == "qwen-plus" && (operation == "llm" || operation == "summary" || operation == "habit") {
		p := QwenPlusBeijing(thinking)
		p.Operation = operation
		return p, nil
	}
	if model == "qwen3-vl-plus" && operation == "vision" {
		return Price{Version: "aliyun-beijing-20261011-vlplus", Region: "cn-beijing", Model: model, Operation: operation, Mode: "non_thinking_or_thinking", SourceURL: "https://help.aliyun.com/zh/model-studio/qwen3-vl-plus", Unit: "tokens", Tiers: []Tier{{32000, "1", "10", "0.2"}, {128000, "1.5", "15", "0.3"}, {256000, "3", "30", "0.6"}}}, nil
	}
	if model == "qwen3-vl-flash" && operation == "vision" {
		return Price{Version: "aliyun-beijing-20261001-v1", Region: "cn-beijing", Model: model, Operation: operation, Mode: "non_thinking_or_thinking", SourceURL: "https://help.aliyun.com/zh/model-studio/model-pricing", Unit: "tokens", Tiers: []Tier{{32000, "0.15", "1.5", "0.03"}, {128000, "0.3", "3", "0.06"}, {256000, "0.6", "6", "0.12"}}}, nil
	}
	if model == "qwen3-asr-flash-realtime" && operation == "asr" {
		return Price{Version: "aliyun-beijing-20261001-v1", Region: "cn-beijing", Model: model, Operation: operation, Mode: "realtime", SourceURL: "https://help.aliyun.com/zh/model-studio/model-pricing", Unit: "audio_second", UnitCNY: "0.00033"}, nil
	}
	if (model == "qwen-audio-3.0-tts-plus" || model == "qwen-audio-3.0-tts-flash") && operation == "tts" {
		rate := Exact("0.00014")
		if model == "qwen-audio-3.0-tts-flash" {
			rate = "0.0001"
		}
		return Price{Version: "aliyun-beijing-20261001-v1", Region: "cn-beijing", Model: model, Operation: operation, Mode: "realtime", SourceURL: "https://help.aliyun.com/zh/model-studio/model-pricing", Unit: "weighted_character", UnitCNY: rate}, nil
	}
	if model == "bailian-memory-lite" {
		return MemoryLite(operation)
	}
	return Price{}, errors.New("hardware_model_or_operation_unverified")
}
