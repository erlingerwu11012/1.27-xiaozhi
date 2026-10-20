package model

// The ledger is shared by the legacy HTTP backend and the native gateway.
// Available balances exclude holds. Usage counters include settled cost only.
import (
	"errors"
	"time"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

const (
	BLReserved  = "reserved"
	BLSubmitted = "submitted"
	BLReview    = "manual_review"
	BLSettled   = "settled"
	BLRefunded  = "refunded"
)

var ErrBLConflict = errors.New("billing_conflict")
var ErrBLQuota = errors.New("insufficient_quota")

type BailianBill struct {
	ID        string `json:"id" gorm:"type:varchar(64);primaryKey"`
	UserID    int    `json:"user_id" gorm:"index"`
	TokenID   int    `json:"token_id" gorm:"index"`
	ChannelID int    `json:"channel_id"`
	Model     string `json:"model" gorm:"type:varchar(160)"`
	Group     string `json:"group" gorm:"type:varchar(32)"`
	Unlimited bool   `json:"unlimited"`
	// Scope is a SHA256 of user, endpoint and the caller's idempotency key.
	Scope         string `json:"-" gorm:"type:char(64);uniqueIndex"`
	PayloadHash   string `json:"-" gorm:"type:char(64)"`
	PriceSnapshot string `json:"price_snapshot" gorm:"type:text"`
	State         string `json:"state" gorm:"type:varchar(24);index"`
	Held          int64  `json:"held"`
	Charged       int64  `json:"charged"`
	LogID         int    `json:"log_id"`
	CreatedAt     int64  `json:"created_at"`
	UpdatedAt     int64  `json:"updated_at" gorm:"index"`
	Reason        string `json:"reason" gorm:"type:varchar(128)"`
}

type BailianAudit struct {
	ID        uint64 `json:"id" gorm:"primaryKey"`
	BillID    string `json:"bill_id" gorm:"type:varchar(64);index"`
	ActorID   int    `json:"actor_id"`
	Action    string `json:"action" gorm:"type:varchar(32)"`
	Reason    string `json:"reason" gorm:"type:text"`
	Charged   int64  `json:"charged"`
	Released  int64  `json:"released"`
	CreatedAt int64  `json:"created_at"`
}

// BailianAdminOp persists admin note/settle operation IDs for idempotency.
type BailianAdminOp struct {
	OperationID   string `json:"operation_id" gorm:"type:varchar(80);primaryKey"`
	BillID        string `json:"bill_id" gorm:"type:varchar(64);index"`
	Kind          string `json:"kind" gorm:"type:varchar(16)"`
	FinalTotal    int64  `json:"final_total"`
	ConfirmZero   bool   `json:"confirm_zero"`
	ActorID       int    `json:"actor_id"`
	Reason        string `json:"reason" gorm:"type:text"`
	Evidence      string `json:"evidence" gorm:"type:text"`
	BeforeHeld    int64  `json:"before_held"`
	BeforeCharged int64  `json:"before_charged"`
	AfterHeld     int64  `json:"after_held"`
	AfterCharged  int64  `json:"after_charged"`
	State         string `json:"state" gorm:"type:varchar(24)"`
	CreatedAt     int64  `json:"created_at"`
}

func (BailianAdminOp) TableName() string { return "bailian_admin_ops" }

// Call only from the explicit migration executable, never server startup.
func MigrateBailianLedger(db *gorm.DB) error {
	return db.AutoMigrate(&BailianBill{}, &BailianAudit{}, &BailianAdminOp{})
}

func blLockWallet(tx *gorm.DB, userID, tokenID int) (*User, *Token, error) {
	var u User
	var t Token
	if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&u, userID).Error; e != nil {
		return nil, nil, e
	}
	if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&t, tokenID).Error; e != nil {
		return nil, nil, e
	}
	if t.UserId != u.Id {
		return nil, nil, ErrBLConflict
	}
	return &u, &t, nil
}

func blAvailable(u *User, t *Token, amount int64) error {
	if amount < 0 {
		return ErrBLConflict
	}
	if u.Status != UserStatusEnabled || t.Status != TokenStatusEnabled || (t.ExpiredTime != -1 && t.ExpiredTime <= time.Now().Unix()) {
		return errors.New("account_or_token_disabled")
	}
	if u.Quota < amount || (!t.UnlimitedQuota && t.RemainQuota < amount) {
		return ErrBLQuota
	}
	return nil
}

func blMoveAvailable(tx *gorm.DB, b *BailianBill, delta int64) error {
	// Positive delta reserves, negative delta releases. All callers hold wallet locks.
	if e := tx.Model(&User{}).Where("id = ?", b.UserID).Update("quota", gorm.Expr("quota - ?", delta)).Error; e != nil {
		return e
	}
	if !b.Unlimited {
		if e := tx.Model(&Token{}).Where("id = ?", b.TokenID).Update("remain_quota", gorm.Expr("remain_quota - ?", delta)).Error; e != nil {
			return e
		}
	}
	return nil
}

// ReserveBailian is idempotent even after an ambiguous database commit.
// The caller must retain ID and Scope when retrying a database operation.
func ReserveBailian(db *gorm.DB, b *BailianBill, amount int64) (reused bool, err error) {
	if b.ID == "" || len(b.Scope) != 64 || len(b.PayloadHash) != 64 || amount <= 0 || b.Model == "" {
		return false, ErrBLConflict
	}
	err = db.Transaction(func(tx *gorm.DB) error {
		if e := guardMigratedLegacyWallet(tx, b.UserID); e != nil {
			return e
		}
		u, t, e := blLockWallet(tx, b.UserID, b.TokenID)
		if e != nil {
			return e
		}
		var prior BailianBill
		e = tx.Where("scope = ?", b.Scope).Take(&prior).Error
		if e == nil {
			if prior.UserID != b.UserID || prior.PayloadHash != b.PayloadHash || prior.Model != b.Model {
				return ErrBLConflict
			}
			*b = prior
			reused = true
			return nil
		}
		if !errors.Is(e, gorm.ErrRecordNotFound) {
			return e
		}
		if e = blAvailable(u, t, amount); e != nil {
			return e
		}
		if b.Group != "" && b.Group != u.Group {
			return ErrBLConflict
		}
		b.Unlimited = t.UnlimitedQuota
		b.Held = amount
		b.State = BLReserved
		b.CreatedAt = time.Now().Unix()
		b.UpdatedAt = b.CreatedAt
		if e = blMoveAvailable(tx, b, amount); e != nil {
			return e
		}
		return tx.Create(b).Error
	})
	return
}

func WithBailianBill(db *gorm.DB, id string, fn func(*gorm.DB, *BailianBill, *User, *Token) error) error {
	// Read immutable ownership first, then lock user -> token -> bill everywhere.
	var owner BailianBill
	if e := db.First(&owner, "id = ?", id).Error; e != nil {
		return e
	}
	if e := guardMigratedLegacyWallet(db, owner.UserID); e != nil {
		return e
	}
	return db.Transaction(func(tx *gorm.DB) error {
		u, t, e := blLockWallet(tx, owner.UserID, owner.TokenID)
		if e != nil {
			return e
		}
		var b BailianBill
		if e = tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&b, "id = ?", id).Error; e != nil {
			return e
		}
		return fn(tx, &b, u, t)
	})
}

// EnsureBailianHold sets a cumulative ceiling, rather than adding a delta twice.
func EnsureBailianHold(db *gorm.DB, id string, total int64) error {
	return WithBailianBill(db, id, func(tx *gorm.DB, b *BailianBill, u *User, t *Token) error {
		if b.State != BLReserved && b.State != BLSubmitted {
			return ErrBLConflict
		}
		if total < 0 || b.Unlimited != t.UnlimitedQuota {
			return ErrBLConflict
		}
		delta := total - b.Charged - b.Held
		if delta <= 0 {
			return nil
		}
		if e := blAvailable(u, t, delta); e != nil {
			return e
		}
		if e := blMoveAvailable(tx, b, delta); e != nil {
			return e
		}
		return tx.Model(b).Updates(map[string]interface{}{"held": b.Held + delta, "updated_at": time.Now().Unix()}).Error
	})
}

// Must commit before any bytes of a chargeable request are sent upstream.
func SubmitBailian(db *gorm.DB, id string) error {
	return WithBailianBill(db, id, func(tx *gorm.DB, b *BailianBill, _ *User, _ *Token) error {
		if b.State == BLSubmitted {
			return nil
		}
		if b.State != BLReserved {
			return ErrBLConflict
		}
		return tx.Model(b).Updates(map[string]interface{}{"state": BLSubmitted, "updated_at": time.Now().Unix()}).Error
	})
}

// ClaimSubmitBailian grants the right to send one chargeable upstream request.
// claimed=true only on reserved → submitted. Already submitted/settled/review
// returns claimed=false so the caller must not send upstream again.
func ClaimSubmitBailian(db *gorm.DB, id string) (claimed bool, err error) {
	err = WithBailianBill(db, id, func(tx *gorm.DB, b *BailianBill, _ *User, _ *Token) error {
		switch b.State {
		case BLSubmitted, BLReview, BLSettled, BLRefunded:
			claimed = false
			return nil
		case BLReserved:
			claimed = true
			return tx.Model(b).Updates(map[string]interface{}{"state": BLSubmitted, "updated_at": time.Now().Unix()}).Error
		default:
			return ErrBLConflict
		}
	})
	return
}

// FinishBailian settles known cost, retaining the unresolved hold on review.
// finalTotal is cumulative and may never exceed the previously reserved ceiling.
// A manual decision requires an enabled administrator and a nonempty rationale.
func FinishBailian(db *gorm.DB, id string, finalTotal int64, review bool, actor int, reason string) error {
	return finishBailian(db, id, finalTotal, review, false, actor, reason)
}

func ConfirmBailian(db *gorm.DB, id string, total int64) error {
	return finishBailian(db, id, total, true, true, 0, "upstream_usage")
}

func finishBailian(db *gorm.DB, id string, finalTotal int64, review, keepOpen bool, actor int, reason string) error {
	return WithBailianBill(db, id, func(tx *gorm.DB, b *BailianBill, u *User, t *Token) error {
		if finalTotal < 0 || len(reason) > 1024 {
			return ErrBLConflict
		}
		if actor != 0 {
			var admin User
			if e := tx.First(&admin, actor).Error; e != nil {
				return e
			}
			if admin.Role < RoleAdminUser || admin.Status != UserStatusEnabled || reason == "" {
				return errors.New("administrator_required")
			}
		}
		if b.State == BLSettled || b.State == BLRefunded {
			if !review && b.Charged == finalTotal {
				return nil
			}
			return ErrBLConflict
		}
		if b.State == BLReview && actor == 0 && !review {
			return errors.New("manual_resolution_required")
		}
		if keepOpen && b.State != BLSubmitted {
			return ErrBLConflict
		}
		if finalTotal < b.Charged || finalTotal-b.Charged > b.Held {
			return ErrBLConflict
		}
		delta := finalTotal - b.Charged
		held := b.Held - delta
		released := int64(0)
		if !review {
			released = held
			held = 0
			if e := blMoveAvailable(tx, b, -released); e != nil {
				return e
			}
		}
		if delta > 0 {
			values := map[string]interface{}{"used_quota": gorm.Expr("used_quota + ?", delta)}
			if b.LogID == 0 {
				values["request_count"] = gorm.Expr("request_count + 1")
			}
			if e := tx.Model(u).Updates(values).Error; e != nil {
				return e
			}
			if e := tx.Model(t).Updates(map[string]interface{}{"used_quota": gorm.Expr("used_quota + ?", delta), "accessed_time": time.Now().Unix()}).Error; e != nil {
				return e
			}
			if e := tx.Model(&Channel{}).Where("id = ?", b.ChannelID).Update("used_quota", gorm.Expr("used_quota + ?", delta)).Error; e != nil {
				return e
			}
		}
		state := BLSettled
		if finalTotal == 0 {
			state = BLRefunded
		}
		if review {
			state = BLReview
		}
		if keepOpen {
			state = BLSubmitted
			if delta == 0 {
				return nil
			}
		}
		if b.LogID == 0 && finalTotal > 0 {
			entry := Log{UserId: b.UserID, TokenName: t.Name, Username: u.Username, ChannelId: b.ChannelID, ModelName: b.Model, Quota: int(finalTotal), Type: LogTypeConsume, RequestId: b.ID, CreatedAt: time.Now().Unix(), Content: "bailian ledger: " + b.ID}
			if e := tx.Create(&entry).Error; e != nil {
				return e
			}
			b.LogID = entry.Id
		} else if b.LogID != 0 {
			if e := tx.Model(&Log{}).Where("id = ?", b.LogID).Update("quota", finalTotal).Error; e != nil {
				return e
			}
		}
		audit := BailianAudit{BillID: b.ID, ActorID: actor, Action: state, Reason: reason, Charged: delta, Released: released, CreatedAt: time.Now().Unix()}
		if e := tx.Create(&audit).Error; e != nil {
			return e
		}
		storedReason := reason
		if len(storedReason) > 128 {
			storedReason = "see_audit"
		}
		return tx.Model(b).Updates(map[string]interface{}{"held": held, "charged": finalTotal, "state": state, "log_id": b.LogID, "reason": storedReason, "updated_at": time.Now().Unix()}).Error
	})
}

// Recover only a quiescent instance's nonterminal requests. Do not run this while
// another gateway instance is serving; ambiguous pre-send crashes stay frozen.
func RecoverBailian(db *gorm.DB, before int64) error {
	return db.Model(&BailianBill{}).Where("state IN ? AND updated_at < ?", []string{BLReserved, BLSubmitted}, before).Updates(map[string]interface{}{"state": BLReview, "reason": "process_recovery", "updated_at": time.Now().Unix()}).Error
}
