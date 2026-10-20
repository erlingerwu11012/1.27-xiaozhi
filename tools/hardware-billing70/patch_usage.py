"""Modify the isolated candidate only; preserve actual upstream meter evidence."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "tmp/hardware-billing70/gateway"

def patch(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    if new in s:
        return
    if s.count(old) != 1:
        raise RuntimeError(f"candidate source mismatch: {path}")
    p.write_text(s.replace(old, new), encoding="utf-8", newline="\n")

patch("relay/model/misc.go", "package model\n\n", '''package model

import "github.com/songquanpeng/one-api/hardwarebilling"

''')
patch("relay/model/misc.go", "type Usage struct {", '''type Usage struct {
    // This evidence is captured BEFORE any legacy token-count fallback.
    // Hardware settlement must use it; the ordinary counters remain compatible.
    ActualEvidence *hardwarebilling.Usage `json:"-"`
    PromptTokensDetails *PromptTokensDetails `json:"prompt_tokens_details,omitempty"`
    CachedTokens *int64 `json:"cached_tokens,omitempty"`
''')
patch("relay/model/misc.go", "type CompletionTokensDetails struct {", '''type PromptTokensDetails struct {
    CachedTokens *int64 `json:"cached_tokens,omitempty"`
}

type CompletionTokensDetails struct {''')

for name in ("ali", "openai"):
    patch(f"relay/adaptor/{name}/main.go", '"encoding/json"', '''"encoding/json"
    "github.com/songquanpeng/one-api/hardwarebilling"''')

patch("relay/adaptor/openai/main.go", "usage = streamResponse.Usage", '''usage = streamResponse.Usage
                evidence, _ := hardwarebilling.ParseUsage([]byte(data[dataPrefixLength:]), streamResponse.Id)
                usage.ActualEvidence = &evidence''')
patch("relay/adaptor/openai/main.go", "// Reset response body", '''// Capture before the legacy fallback below. Missing actual usage remains pending.
    evidence, _ := hardwarebilling.ParseUsage(responseBody, resp.Header.Get("X-Request-Id"))
    textResponse.Usage.ActualEvidence = &evidence

    // Reset response body''')
patch("relay/adaptor/openai/main.go", "return nil, &textResponse.Usage", '''textResponse.Usage.ActualEvidence = &evidence
    return nil, &textResponse.Usage''')

patch("relay/adaptor/ali/model.go", "type Usage struct {", '''type Usage struct {
    CachedTokens *int64 `json:"cached_tokens,omitempty"`
    PromptTokensDetails *model.PromptTokensDetails `json:"prompt_tokens_details,omitempty"`
''')
# Ali's model.go already imports relay/model? Add only if absent.
p = ROOT / "relay/adaptor/ali/model.go"
s = p.read_text(encoding="utf-8")
if '"github.com/songquanpeng/one-api/relay/model"' not in s:
    if "import (" in s:
        s = s.replace("import (", 'import (\n"github.com/songquanpeng/one-api/relay/model"', 1)
    else:
        # Existing single import must become a block, rather than adding a second package.
        s = s.replace('import "github.com/songquanpeng/one-api/relay/adaptor/openai"', 'import (\n"github.com/songquanpeng/one-api/relay/adaptor/openai"\n"github.com/songquanpeng/one-api/relay/model"\n)', 1)
    p.write_text(s, encoding="utf-8", newline="\n")

patch("relay/adaptor/ali/main.go", "TotalTokens:      response.Usage.InputTokens + response.Usage.OutputTokens,", '''TotalTokens:      response.Usage.InputTokens + response.Usage.OutputTokens,
            CachedTokens: response.Usage.CachedTokens,
            PromptTokensDetails: response.Usage.PromptTokensDetails,''')
patch("relay/adaptor/ali/main.go", "if aliResponse.Usage.OutputTokens != 0 {", '''evidence, meterErr := hardwarebilling.ParseUsage([]byte(data), aliResponse.RequestId)
        if evidence.UpstreamRequestID != "" && (meterErr == nil || evidence.Input > 0) {
            usage.ActualEvidence = &evidence
            usage.CachedTokens = evidence.Cached
            if evidence.Cached != nil {
                usage.PromptTokensDetails = &model.PromptTokensDetails{CachedTokens: evidence.Cached}
            }
        }
        if aliResponse.Usage.OutputTokens != 0 {''')
patch("relay/adaptor/ali/main.go", "fullTextResponse := responseAli2OpenAI(&aliResponse)", '''fullTextResponse := responseAli2OpenAI(&aliResponse)
    evidence, _ := hardwarebilling.ParseUsage(responseBody, aliResponse.RequestId)
    fullTextResponse.Usage.ActualEvidence = &evidence''')

print("candidate upstream-meter propagation patched")
