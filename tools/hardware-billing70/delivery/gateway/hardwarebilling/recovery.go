package hardwarebilling

import (
	"context"
	"encoding/json"
	"errors"
	"gorm.io/gorm"
	"time"
)

// This stores meters only, never prompts, audio, portraits or upstream keys.
func (l Ledger) RecordEvidence(user int, id string, u Usage, legacy Exact) error {
	raw, e := json.Marshal(u)
	if e != nil {
		return e
	}
	digest := hash(raw)
	if _, e = Parse(string(legacy)); e != nil {
		return e
	}
	return l.DB.Transaction(func(tx *gorm.DB) error {
		if e := lockedWallet(tx, user); e != nil {
			return e
		}
		var b Bill
		if e := tx.First(&b, "id = ? AND user_id = ?", id, user).Error; e != nil {
			return e
		}
		if b.State == "settled" || b.State == "refunded" {
			if b.UsageHash != digest {
				return errors.New("usage_idempotency_conflict")
			}
			return nil
		}
		if b.State != "reserved" && b.State != "pending" && b.State != "outstanding" {
			return errors.New("invalid_bill_state")
		}
		if b.UsageHash != "" && b.UsageHash != digest {
			return errors.New("usage_idempotency_conflict")
		}
		var price Price
		if e := json.Unmarshal([]byte(b.PriceJSON), &price); e != nil {
			return e
		}
		if _, e := price.Cost(u); e == nil {
			if b.UsageHash != "" && b.SettlementLegacyDebit != "" && b.SettlementLegacyDebit != string(legacy) {
				return errors.New("legacy_debit_idempotency_conflict")
			}
			b.UsageHash = digest
		}
		b.UsageJSON = string(raw)
		b.SettlementLegacyDebit = string(legacy)
		if b.State == "reserved" {
			b.State = "pending"
		}
		return tx.Save(&b).Error
	})
}

// Only verified receipts are replayed. Unknown usage stays pending; this worker
// never calls the model again and never invents an upstream cost.
func (l Ledger) RecoverConfirmed(limit int) (int, error) {
	if limit < 1 || limit > 1000 {
		return 0, errors.New("invalid_recovery_limit")
	}
	var rows []Bill
	e := l.DB.Where("state IN ? AND usage_hash <> '' AND settlement_legacy_debit <> ''", []string{"pending", "outstanding"}).Order("created_at,id").Limit(limit).Find(&rows).Error
	if e != nil {
		return 0, e
	}
	done := 0
	for _, b := range rows {
		var u Usage
		if e := json.Unmarshal([]byte(b.UsageJSON), &u); e != nil {
			continue
		}
		var p Price
		if e := json.Unmarshal([]byte(b.PriceJSON), &p); e != nil {
			continue
		}
		if _, e := p.Cost(u); e != nil {
			continue
		}
		result, e := l.Settle(b.UserID, b.ID, u, Exact(b.SettlementLegacyDebit))
		if e == nil && result.State == "settled" {
			done++
		}
	}
	return done, nil
}

func RunRecovery(ctx context.Context, db *gorm.DB) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			work, cancel := context.WithTimeout(ctx, 20*time.Second)
			_, _ = (Ledger{DB: db.WithContext(work)}).RecoverConfirmed(100)
			cancel()
		}
	}
}
