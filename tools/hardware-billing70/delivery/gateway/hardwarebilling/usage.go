package hardwarebilling

import (
	"encoding/json"
	"errors"
)

// ParseUsage accepts only upstream response envelopes. It does not parse or
// persist messages, audio, prompts or authorization headers.
func ParseUsage(raw []byte, requestID string) (Usage, error) {
	var env struct {
		ID        string `json:"id"`
		RequestID string `json:"request_id"`
		Usage     *struct {
			Input         *int64       `json:"input_tokens"`
			Output        *int64       `json:"output_tokens"`
			Prompt        *int64       `json:"prompt_tokens"`
			Completion    *int64       `json:"completion_tokens"`
			Total         *int64       `json:"total_tokens"`
			Cached        *int64       `json:"cached_tokens"`
			NativeCached  *int64       `json:"input_tokens_cached"`
			Characters    *json.Number `json:"characters"`
			Duration      *json.Number `json:"duration"`
			PromptDetails *struct {
				Cached *int64 `json:"cached_tokens"`
			} `json:"prompt_tokens_details"`
			CompletionDetails *struct {
				Reasoning *int64 `json:"reasoning_tokens"`
			} `json:"completion_tokens_details"`
		} `json:"usage"`
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return Usage{}, errors.New("invalid_usage_envelope")
	}
	if env.RequestID != "" {
		requestID = env.RequestID
	} else if env.ID != "" {
		requestID = env.ID
	}
	result := Usage{Source: "upstream", UpstreamRequestID: requestID}
	if env.Usage == nil || requestID == "" {
		return result, errors.New("usage_pending")
	}
	u := env.Usage
	if u.Characters != nil || u.Duration != nil {
		n := u.Characters
		if n == nil {
			n = u.Duration
		}
		r, err := Parse(n.String())
		if err != nil {
			return result, err
		}
		result.Units = exact(r)
		result.Confirmed = true
		return result, nil
	}
	in, out := u.Input, u.Output
	if in == nil {
		in = u.Prompt
	}
	if out == nil {
		out = u.Completion
	}
	if in == nil || out == nil || *in < 0 || *out < 0 {
		return result, errors.New("usage_pending")
	}
	cached := u.Cached
	if cached == nil {
		cached = u.NativeCached
	}
	if u.PromptDetails != nil && u.PromptDetails.Cached != nil {
		cached = u.PromptDetails.Cached
	}
	result.Input = *in
	result.Output = *out
	result.Cached = cached
	if u.CompletionDetails != nil {
		result.Reasoning = u.CompletionDetails.Reasoning
	}
	if cached == nil {
		return result, errors.New("cache_usage_pending")
	}
	// Checked without addition overflow.
	if *cached < 0 || *cached > *in || (u.Total != nil && (*u.Total < *in || *u.Total-*in != *out)) {
		return result, errors.New("invalid_usage")
	}
	if result.Reasoning != nil && (*result.Reasoning < 0 || *result.Reasoning > *out) {
		return result, errors.New("invalid_usage")
	}
	result.Confirmed = true
	return result, nil
}
