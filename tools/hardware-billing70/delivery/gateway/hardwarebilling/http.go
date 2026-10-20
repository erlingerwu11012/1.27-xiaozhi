package hardwarebilling

import (
	"encoding/json"
	"errors"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
	"strconv"
	"time"
)

// PrepareHTTP receives the user ID ONLY from the existing validated gateway
// token context. An enabled wallet cannot fall back to the legacy charge path.
func (l Ledger) PrepareHTTP(c *gin.Context, enabled bool, key []byte, user int,
	raw []byte, price Price, holdSale, holdLegacy Exact) (*Bill, error) {
	hasProof := c.GetHeader("X-HW-Account") != "" || c.GetHeader("X-HW-Signature") != ""
	if !enabled {
		if hasProof {
			return nil, errors.New("hardware_billing_disabled")
		}
		return nil, nil
	}
	var wallet Wallet
	e := l.DB.First(&wallet, "user_id = ?", user).Error
	if errors.Is(e, gorm.ErrRecordNotFound) {
		if hasProof {
			return nil, errors.New("hardware_wallet_not_enabled")
		}
		return nil, nil
	}
	if e != nil {
		return nil, e
	}
	if wallet.State != "enabled" {
		return nil, errors.New("hardware_wallet_disabled")
	}
	if !hasProof {
		return nil, errors.New("hardware_service_proof_required")
	}
	p := ServiceProof{Timestamp: c.GetHeader("X-HW-Timestamp"), RequestID: c.GetHeader("X-HW-Request-ID"), ProductAccount: c.GetHeader("X-HW-Account"), Operation: c.GetHeader("X-HW-Operation"), Signature: c.GetHeader("X-HW-Signature")}
	account, e := strconv.ParseInt(p.ProductAccount, 10, 64)
	if e != nil || account <= 0 || wallet.ProductAccount != p.ProductAccount {
		return nil, errors.New("hardware_account_ownership_mismatch")
	}
	if p.Operation != price.Operation {
		return nil, errors.New("hardware_operation_mismatch")
	}
	if e := VerifyProof(key, c.Request.Method, c.Request.URL.RequestURI(), raw, p, time.Now()); e != nil {
		return nil, e
	}
	b, e := l.Begin(user, p.RequestID, hash(raw), price, holdSale, holdLegacy)
	if e != nil {
		return nil, e
	}
	if b.Replay {
		return nil, errors.New("hardware_request_already_accepted")
	}
	return &b, nil
}

// CancelBeforeDispatch may ONLY be used for a local failure before contacting
// upstream. Network timeouts/unknown results remain pending with their hold.
func (l Ledger) CancelBeforeDispatch(user int, id string) error {
	return l.DB.Transaction(func(tx *gorm.DB) error {
		if e := lockedWallet(tx, user); e != nil {
			return e
		}
		var b Bill
		if e := tx.First(&b, "id = ? AND user_id = ?", id, user).Error; e != nil {
			return e
		}
		if b.State == "cancelled" {
			return nil
		}
		if b.State != "reserved" || b.UsageJSON != "" {
			return errors.New("cannot_cancel_dispatched_bill")
		}
		var held []Allocation
		if e := json.Unmarshal([]byte(b.Allocations), &held); e != nil {
			return e
		}
		if e := alter(tx, user, held, true); e != nil {
			return e
		}
		b.State = "cancelled"
		b.Allocations = "[]"
		b.SettledAt = time.Now().Unix()
		return tx.Save(&b).Error
	})
}
