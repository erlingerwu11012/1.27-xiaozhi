package hardwarebilling

import (
	"strings"
	"testing"
	"time"
)

func TestServiceProofBindsPayloadAndOwner(t *testing.T) {
	key := []byte(strings.Repeat("synthetic-test-", 3))
	now := time.Unix(1790820000, 0)
	p := ServiceProof{Timestamp: "1790820000", RequestID: "r1", ProductAccount: "account1", Operation: "llm"}
	var e error
	p.Signature, e = SignProof(key, "POST", "/v1/chat/completions", []byte("synthetic"), p)
	if e != nil {
		t.Fatal(e)
	}
	if e := VerifyProof(key, "POST", "/v1/chat/completions", []byte("synthetic"), p, now); e != nil {
		t.Fatal(e)
	}
	if e := VerifyProof(key, "POST", "/v1/chat/completions", []byte("changed"), p, now); e == nil {
		t.Fatal("body not bound")
	}
	p.ProductAccount = "account2"
	if e := VerifyProof(key, "POST", "/v1/chat/completions", []byte("synthetic"), p, now); e == nil {
		t.Fatal("owner not bound")
	}
	p.ProductAccount = "account1"
	if e := VerifyProof(key, "POST", "/v1/chat/completions", []byte("synthetic"), p, now.Add(61*time.Second)); e == nil {
		t.Fatal("expired proof accepted")
	}
}
