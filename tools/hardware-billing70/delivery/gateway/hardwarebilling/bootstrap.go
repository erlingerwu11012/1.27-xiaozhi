package hardwarebilling

import (
	"errors"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"math/big"
	"time"
)

// Bootstrap must run in a paused, verified cutover transaction after binding
// ownership has been checked. It never guesses a person or transfers Aimi funds.
// originalQuota is an exact locked snapshot (500 quota per old point).
func (l Ledger) Bootstrap(user int, account string, originalQuota int64, usedSnapshot ...int64) error {
	if user <= 0 || account == "" || len(account) > 64 || originalQuota < 0 {
		return errors.New("invalid_wallet_snapshot")
	}
	used := int64(0)
	if len(usedSnapshot) > 1 {
		return errors.New("invalid_used_snapshot")
	}
	if len(usedSnapshot) == 1 {
		used = usedSnapshot[0]
	}
	if used < 0 {
		return errors.New("invalid_used_snapshot")
	}
	return l.DB.Transaction(func(tx *gorm.DB) error {
		var old Wallet
		e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&old, "user_id = ?", user).Error
		if e == nil {
			if old.ProductAccount != account {
				return errors.New("wallet_binding_conflict")
			}
			return nil
		}
		if !errors.Is(e, gorm.ErrRecordNotFound) {
			return e
		}
		if e := tx.Create(&Wallet{UserID: user, ProductAccount: account, State: "enabled", CreatedAt: time.Now().Unix(), LegacyUsedQuota: used}).Error; e != nil {
			return e
		}
		amount := new(big.Rat).SetFrac(big.NewInt(originalQuota), big.NewInt(500))
		return tx.Create(&StoredLot{ID: "legacy:" + account, UserID: user, Kind: "legacy", Remaining: amount.RatString(), OriginalPoints: amount.RatString(), CNYPerPoint: "0", CreatedAt: time.Now().UnixNano()}).Error
	})
}

// A zero-cash gift stays in the legacy bucket: no invented cash rate or margin.
// The external verified grant id is mandatory for replay-safe administration.
func (l Ledger) GrantLegacy(user int, grantID string, points Exact) error {
	amount, e := Parse(string(points))
	if e != nil {
		return e
	}
	if grantID == "" || len(grantID) > 100 {
		return errors.New("invalid_grant_id")
	}
	return l.DB.Transaction(func(tx *gorm.DB) error {
		if e := lockedWallet(tx, user); e != nil {
			return e
		}
		id := "gift:" + grantID
		var prior StoredLot
		e := tx.First(&prior, "id = ?", id).Error
		if e == nil {
			if prior.UserID != user || prior.Kind != "legacy" || prior.CNYPerPoint != "0" || prior.OriginalPoints != amount.RatString() {
				return errors.New("grant_idempotency_conflict")
			}
			return nil
		}
		if !errors.Is(e, gorm.ErrRecordNotFound) {
			return e
		}
		return tx.Create(&StoredLot{ID: id, UserID: user, Kind: "legacy", Remaining: amount.RatString(), OriginalPoints: amount.RatString(), CNYPerPoint: "0", CreatedAt: time.Now().UnixNano()}).Error
	})
}
