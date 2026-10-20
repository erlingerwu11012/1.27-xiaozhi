package hardwarebilling

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"time"
)

type Wallet struct {
	UserID          int    `gorm:"primaryKey"`
	ProductAccount  string `gorm:"type:varchar(64);uniqueIndex"`
	State           string `gorm:"type:varchar(24)"`
	CreatedAt       int64
	LegacyUsedQuota int64 `gorm:"not null;default:0"`
}

func (Wallet) TableName() string { return "hardware_billing_wallet" }

type StoredLot struct {
	ID             string `gorm:"type:varchar(128);primaryKey"`
	UserID         int    `gorm:"index"`
	Kind           string `gorm:"type:varchar(16)"`
	Remaining      string `gorm:"type:text"`
	CNYPerPoint    string `gorm:"type:text"`
	PaidCents      int64
	GrantedPoints  int64
	OriginalPoints string `gorm:"type:text"`
	CreatedAt      int64
}

func (StoredLot) TableName() string { return "hardware_billing_lot" }

type Bill struct {
	ID                    string `gorm:"type:varchar(128);primaryKey"`
	UserID                int    `gorm:"index"`
	PayloadHash           string `gorm:"type:char(64)"`
	PriceJSON             string `gorm:"type:text"`
	UsageJSON             string `gorm:"type:text"`
	UsageHash             string `gorm:"type:char(64)"`
	SettlementLegacyDebit string `gorm:"type:text"`
	State                 string `gorm:"type:varchar(24);index"`
	CostCNY               string `gorm:"type:text"`
	SaleCNY               string `gorm:"type:text"`
	Allocations           string `gorm:"type:text"`
	ReservationJSON       string `gorm:"type:text"`
	Replay                bool   `gorm:"-"`
	CreatedAt             int64  `gorm:"index"`
	SettledAt             int64
}

func (Bill) TableName() string { return "hardware_billing_bill" }

type Adjustment struct {
	ID          string `gorm:"type:varchar(128);primaryKey"`
	BillID      string `gorm:"type:varchar(128);index"`
	UserID      int    `gorm:"index"`
	Kind        string `gorm:"type:varchar(24)"`
	Allocations string `gorm:"type:text"`
	CreatedAt   int64
}

func (Adjustment) TableName() string { return "hardware_billing_adjustment" }

type Ledger struct{ DB *gorm.DB }

// Migrations are run explicitly in the candidate environment; production must
// use the reviewed migration, not implicit startup AutoMigrate.
func (l Ledger) Migrate() error {
	return l.DB.AutoMigrate(&Wallet{}, &StoredLot{}, &Bill{}, &Adjustment{})
}
func hash(b []byte) string { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }
func lockedWallet(tx *gorm.DB, user int) error {
	var w Wallet
	if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&w, "user_id = ?", user).Error; e != nil {
		return e
	}
	if w.State != "enabled" {
		return errors.New("hardware_wallet_disabled")
	}
	return nil
}
func loadLots(tx *gorm.DB, user int) ([]Lot, error) {
	var stored []StoredLot
	if e := tx.Where("user_id = ?", user).Order("CASE WHEN kind = 'legacy' THEN 0 ELSE 1 END, created_at, id").Find(&stored).Error; e != nil {
		return nil, e
	}
	result := make([]Lot, 0, len(stored))
	for _, s := range stored {
		result = append(result, Lot{s.ID, s.Kind, Exact(s.Remaining), Exact(s.CNYPerPoint)})
	}
	return result, nil
}
func alter(tx *gorm.DB, user int, alloc []Allocation, refund bool) error {
	for _, a := range alloc {
		var lot StoredLot
		if e := tx.First(&lot, "id = ? AND user_id = ?", a.LotID, user).Error; e != nil {
			return e
		}
		balance, e := Parse(lot.Remaining)
		if e != nil {
			return e
		}
		points, e := Parse(string(a.Points))
		if e != nil {
			return e
		}
		if refund {
			balance.Add(balance, points)
		} else {
			balance.Sub(balance, points)
		}
		if balance.Sign() < 0 {
			return errors.New("insufficient_balance")
		}
		if e := tx.Model(&StoredLot{}).Where("id = ? AND user_id = ?", a.LotID, user).Update("remaining", balance.RatString()).Error; e != nil {
			return e
		}
	}
	return mirrorAvailable(tx, user)
}

// Recharge is called only after a verified delivered payment snapshot. It must
// share the account lock with consumption. An order id cannot change its cash
// or points snapshot on a retry.
func (l Ledger) Recharge(user int, order string, cents, points int64) error {
	rate, e := CashRate(cents, points)
	if e != nil {
		return e
	}
	if order == "" {
		return errors.New("missing_order_id")
	}
	return l.DB.Transaction(func(tx *gorm.DB) error {
		if e := lockedWallet(tx, user); e != nil {
			return e
		}
		id := "payment:" + order
		var old StoredLot
		e := tx.First(&old, "id = ?", id).Error
		if e == nil {
			if old.UserID != user || old.PaidCents != cents || old.GrantedPoints != points {
				return errors.New("recharge_idempotency_conflict")
			}
			return nil
		}
		if !errors.Is(e, gorm.ErrRecordNotFound) {
			return e
		}
		return tx.Create(&StoredLot{ID: id, UserID: user, Kind: "paid", Remaining: integer(points).RatString(), OriginalPoints: integer(points).RatString(), CNYPerPoint: string(rate), PaidCents: cents, GrantedPoints: points, CreatedAt: time.Now().UnixNano()}).Error
	})
}

// Begin stores a frozen price and reservation. Estimation is only a hold; it is
// never recorded as final upstream usage or cost.
func (l Ledger) Begin(user int, id, payloadHash string, price Price, holdSale, holdLegacy Exact) (Bill, error) {
	var b Bill
	if id == "" || len(id) > 128 || len(payloadHash) != 64 {
		return b, errors.New("invalid_request_id")
	}
	p, e := json.Marshal(price)
	if e != nil {
		return b, e
	}
	e = l.DB.Transaction(func(tx *gorm.DB) error {
		if e := lockedWallet(tx, user); e != nil {
			return e
		}
		e := tx.First(&b, "id = ?", id).Error
		if e == nil {
			if b.UserID != user || b.PayloadHash != payloadHash {
				return errors.New("request_idempotency_conflict")
			}
			b.Replay = true
			return nil
		}
		if !errors.Is(e, gorm.ErrRecordNotFound) {
			return e
		}
		var debts int64
		if e := tx.Model(&Bill{}).Where("user_id = ? AND state = ?", user, "outstanding").Count(&debts).Error; e != nil {
			return e
		}
		if debts > 0 {
			return errors.New("outstanding_usage_requires_settlement")
		}
		lots, e := loadLots(tx, user)
		if e != nil {
			return e
		}
		a, e := Allocate(lots, holdSale, holdLegacy)
		if e != nil {
			return e
		}
		if e := alter(tx, user, a, false); e != nil {
			return e
		}
		encoded, e := json.Marshal(a)
		if e != nil {
			return e
		}
		b = Bill{ID: id, UserID: user, PayloadHash: payloadHash, PriceJSON: string(p), State: "reserved", Allocations: string(encoded), ReservationJSON: string(encoded), CreatedAt: time.Now().Unix()}
		return tx.Create(&b).Error
	})
	return b, e
}

// Settle releases the reservation and applies actual usage within ONE database
// transaction. A duplicate completion cannot charge twice. If insufficient,
// actual evidence is retained with the reservation in an outstanding state.
func (l Ledger) Settle(user int, id string, usage Usage, legacyDebit Exact) (Bill, error) {
	var b Bill
	encoded, e := json.Marshal(usage)
	if e != nil {
		return b, e
	}
	digest := hash(encoded)
	// Keep official evidence independently of the debit transaction. A temporary
	// balance/database failure must not discard the only upstream receipt.
	if e = l.RecordEvidence(user, id, usage, legacyDebit); e != nil {
		return b, e
	}
	e = l.DB.Transaction(func(tx *gorm.DB) error {
		if e := lockedWallet(tx, user); e != nil {
			return e
		}
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
		var p Price
		if e := json.Unmarshal([]byte(b.PriceJSON), &p); e != nil {
			return e
		}
		cost, e := p.Cost(usage)
		if e != nil {
			b.State = "pending"
			b.UsageJSON = string(encoded)
			return tx.Save(&b).Error
		}
		sale, e := SaleCNY(cost)
		if e != nil {
			return e
		}
		var held []Allocation
		if e := json.Unmarshal([]byte(b.Allocations), &held); e != nil {
			return e
		}
		lots, e := loadLots(tx, user)
		if e != nil {
			return e
		}
		// Preview after release without changing stored lots. Insufficiency must
		// persist usage evidence, not roll it back together with the debit.
		for _, reservation := range held {
			found := false
			for i := range lots {
				if lots[i].ID == reservation.LotID {
					amount, e := Parse(string(lots[i].Remaining))
					if e != nil {
						return e
					}
					points, e := Parse(string(reservation.Points))
					if e != nil {
						return e
					}
					lots[i].Remaining = exact(amount.Add(amount, points))
					found = true
					break
				}
			}
			if !found {
				return errors.New("reservation_lot_missing")
			}
		}
		a, e := Allocate(lots, sale, legacyDebit)
		if e != nil {
			if e.Error() != "insufficient_balance" {
				return e
			}
			b.State = "outstanding"
			b.CostCNY = string(cost)
			b.SaleCNY = string(sale)
			b.UsageJSON = string(encoded)
			b.UsageHash = digest
			return tx.Save(&b).Error
		}
		if e := alter(tx, user, held, true); e != nil {
			return e
		}
		if e := alter(tx, user, a, false); e != nil {
			return e
		}
		splits, e := json.Marshal(a)
		if e != nil {
			return e
		}
		b.State = "settled"
		b.CostCNY = string(cost)
		b.SaleCNY = string(sale)
		b.UsageJSON = string(encoded)
		b.UsageHash = digest
		b.Allocations = string(splits)
		b.SettledAt = time.Now().Unix()
		return tx.Save(&b).Error
	})
	return b, e
}

// Refund creates an immutable compensation record and restores the original
// lots; it never deletes the bill or recreates a payment at today's price.
func (l Ledger) Refund(user int, id, adjustmentID string) error {
	if adjustmentID == "" {
		return errors.New("missing_adjustment_id")
	}
	return l.DB.Transaction(func(tx *gorm.DB) error {
		if e := lockedWallet(tx, user); e != nil {
			return e
		}
		var b Bill
		if e := tx.First(&b, "id = ? AND user_id = ?", id, user).Error; e != nil {
			return e
		}
		var prior Adjustment
		e := tx.First(&prior, "id = ?", adjustmentID).Error
		if e == nil {
			if prior.BillID != id || prior.UserID != user {
				return errors.New("refund_idempotency_conflict")
			}
			return nil
		}
		if !errors.Is(e, gorm.ErrRecordNotFound) {
			return e
		}
		if b.State == "refunded" || b.State == "cancelled" {
			return errors.New("already_compensated")
		}
		if b.State != "settled" && b.State != "reserved" && b.State != "pending" && b.State != "outstanding" {
			return errors.New("invalid_bill_state")
		}
		var a []Allocation
		if e := json.Unmarshal([]byte(b.Allocations), &a); e != nil {
			return e
		}
		if e := alter(tx, user, a, true); e != nil {
			return e
		}
		kind := "release"
		state := "cancelled"
		if b.State == "settled" {
			kind = "refund"
			state = "refunded"
		}
		if e := tx.Create(&Adjustment{ID: adjustmentID, BillID: id, UserID: user, Kind: kind, Allocations: b.Allocations, CreatedAt: time.Now().Unix()}).Error; e != nil {
			return e
		}
		return tx.Model(&b).Update("state", state).Error
	})
}
