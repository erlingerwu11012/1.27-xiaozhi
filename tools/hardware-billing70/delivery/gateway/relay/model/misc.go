package model

import "github.com/songquanpeng/one-api/hardwarebilling"

type Usage struct {
	// This evidence is captured BEFORE any legacy token-count fallback.
	// Hardware settlement must use it; the ordinary counters remain compatible.
	ActualEvidence      *hardwarebilling.Usage `json:"-"`
	PromptTokensDetails *PromptTokensDetails   `json:"prompt_tokens_details,omitempty"`
	CachedTokens        *int64                 `json:"cached_tokens,omitempty"`

	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`

	CompletionTokensDetails *CompletionTokensDetails `json:"completion_tokens_details,omitempty"`
}

type PromptTokensDetails struct {
	CachedTokens *int64 `json:"cached_tokens,omitempty"`
}

type CompletionTokensDetails struct {
	ReasoningTokens          int `json:"reasoning_tokens"`
	AcceptedPredictionTokens int `json:"accepted_prediction_tokens"`
	RejectedPredictionTokens int `json:"rejected_prediction_tokens"`
}

type Error struct {
	Message string `json:"message"`
	Type    string `json:"type"`
	Param   string `json:"param"`
	Code    any    `json:"code"`
}

type ErrorWithStatusCode struct {
	Error
	StatusCode int `json:"status_code"`
}
