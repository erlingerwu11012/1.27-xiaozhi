package hardwarebilling

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strconv"
	"strings"
	"time"
)

// ServiceProof authenticates the product service in addition to the existing
// user's One API token. Account ownership must STILL be derived from the token
// and verified against the product binding; proof never authorizes an arbitrary
// user_id. All fields are bound to the exact request body and operation.
type ServiceProof struct {
	Timestamp      string
	RequestID      string
	ProductAccount string
	Operation      string
	Signature      string
}

func signatureInput(method, path, bodyHash string, p ServiceProof) string {
	return strings.Join([]string{method, path, bodyHash, p.Timestamp, p.RequestID, p.ProductAccount, p.Operation}, "\n")
}
func validProofFields(p ServiceProof) bool {
	for _, s := range []string{p.Timestamp, p.RequestID, p.ProductAccount, p.Operation} {
		if s == "" || len(s) > 128 || strings.ContainsAny(s, "\r\n") {
			return false
		}
	}
	return true
}
func SignProof(key []byte, method, path string, body []byte, p ServiceProof) (string, error) {
	if len(key) < 32 || !validProofFields(p) {
		return "", errors.New("invalid_service_proof")
	}
	m := hmac.New(sha256.New, key)
	m.Write([]byte(signatureInput(method, path, hash(body), p)))
	return hex.EncodeToString(m.Sum(nil)), nil
}
func VerifyProof(key []byte, method, path string, body []byte, p ServiceProof, now time.Time) error {
	ts, e := strconv.ParseInt(p.Timestamp, 10, 64)
	if e != nil || ts < now.Unix()-60 || ts > now.Unix()+60 {
		return errors.New("expired_service_proof")
	}
	expected, e := SignProof(key, method, path, body, p)
	if e != nil {
		return e
	}
	supplied, e := hex.DecodeString(p.Signature)
	if e != nil {
		return errors.New("invalid_service_proof")
	}
	actual, _ := hex.DecodeString(expected)
	if !hmac.Equal(actual, supplied) {
		return errors.New("invalid_service_proof")
	}
	return nil
}
