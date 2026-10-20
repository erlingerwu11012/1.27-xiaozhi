package bailian

import (
	"encoding/json"
	"errors"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"math/big"
	"time"
)

const memoryPriceVersion = "aliyun-20260929-sale-1.43-v1"

type MemoryEntity struct {
	CloudUserID      string `gorm:"type:varchar(128);primaryKey"`
	UserID           int    `gorm:"index"`
	TokenID          int
	ProductAccount   string `gorm:"type:varchar(64);index"`
	PersonID         string `gorm:"type:varchar(64)"`
	Generation       int64
	State            string `gorm:"type:varchar(24)"`
	PortraitWritten  bool
	CleanupConfirmed bool
	CreatedAt        int64
}
type MemoryResource struct {
	Kind        string `gorm:"type:varchar(24);primaryKey"`
	ID          string `gorm:"type:varchar(128);primaryKey"`
	CloudUserID string `gorm:"type:varchar(128);index"`
	UserID      int    `gorm:"index"`
}
type MemoryRequest struct {
	ID          string `gorm:"type:char(64);primaryKey"`
	UserID      int    `gorm:"index"`
	CloudUserID string `gorm:"type:varchar(128);index"`
	PayloadHash string `gorm:"type:char(64)"`
	Path        string `gorm:"type:varchar(256)"`
	State       string `gorm:"type:varchar(24);index"`
	Status      int
	Response    string `gorm:"type:mediumtext"`
	RequestID   string `gorm:"type:varchar(128)"`
	EventID     string `gorm:"type:varchar(128)"`
	EventState  string `gorm:"type:varchar(24)"`
	CreatedAt   int64
}
type MemoryCharge struct {
	ID          string `gorm:"type:char(64);primaryKey"`
	RequestID   string `gorm:"type:char(64);index"`
	BillID      string `gorm:"type:varchar(64);uniqueIndex"`
	UserID      int    `gorm:"index"`
	CloudUserID string `gorm:"type:varchar(128);index"`
	Operation   string `gorm:"type:varchar(24)"`
	Strategy    string `gorm:"type:varchar(16)"`
	Version     string `gorm:"type:varchar(80)"`
	UpstreamCNY string `gorm:"type:varchar(64)"`
	Multiplier  string `gorm:"type:varchar(16)"`
	ExactQuota  string `gorm:"type:varchar(128)"`
	State       string `gorm:"type:varchar(24)"`
	Units       int64
	CreatedAt   int64
}
type MemoryRemainder struct {
	UserID     int    `gorm:"primaryKey"`
	ExactQuota string `gorm:"type:varchar(128)"`
}
type MemoryStorageHour struct {
	ID                string `gorm:"type:char(64);primaryKey"`
	CloudUserID       string `gorm:"type:varchar(128);index"`
	UserID            int    `gorm:"index"`
	TokenID           int
	ChannelID         int
	Hour              int64 `gorm:"index"`
	FactCount         int64
	PortraitCount     int64
	State             string `gorm:"type:varchar(24);index"`
	ExactQuota        string `gorm:"type:varchar(128)"`
	BillID            string `gorm:"type:varchar(64)"`
	EvidenceRequestID string `gorm:"type:varchar(128)"`
	SampledAt         int64
}

func MigrateMemoryProduct(db *gorm.DB) error {
	return db.AutoMigrate(&MemoryEntity{}, &MemoryResource{}, &MemoryRequest{}, &MemoryCharge{}, &MemoryRemainder{}, &MemoryStorageHour{}, &MemoryResolution{})
}

func memoryUnitPrice(operation, strategy string) (string, error) {
	if strategy != "lite" && strategy != "pro" {
		return "", errors.New("invalid_strategy")
	}
	switch operation {
	case "fact":
		if strategy == "lite" {
			return "0.018", nil
		}
		return "0.03", nil
	case "portrait":
		if strategy == "lite" {
			return "0.025", nil
		}
		return "0.03", nil
	case "search":
		if strategy == "lite" {
			return "0.00002", nil
		}
		return "0.001", nil
	case "storage":
		return "0.002", nil
	}
	return "", errors.New("unknown_memory_operation")
}
func memoryExactQuota(operation, strategy string, units int64) (*big.Rat, error) {
	price, e := memoryUnitPrice(operation, strategy)
	if e != nil || units < 0 {
		return nil, errors.New("invalid_memory_price")
	}
	value, _ := new(big.Rat).SetString(price)
	value.Mul(value, big.NewRat(143, 100)) // sale multiplier exactly once, no group/model multiplier
	value.Mul(value, big.NewRat(500000, 7))
	value.Mul(value, big.NewRat(units, 1))
	if operation == "storage" {
		value.Quo(value, big.NewRat(10000, 1))
	}
	return value, nil
}
func quotaFloor(value *big.Rat) int64 { return new(big.Int).Quo(value.Num(), value.Denom()).Int64() }
func quotaCeil(value *big.Rat) int64 {
	n := quotaFloor(value)
	if new(big.Rat).SetInt64(n).Cmp(value) < 0 {
		n++
	}
	return n
}

func (g *Gateway) reserveMemoryCharge(p Principal, ch model.Channel, request *MemoryRequest, operation, strategy string, units int64) (*MemoryCharge, error) {
	if c, handled, e := g.reserveHardwareMemory(p, request, operation, strategy, units); handled {
		return c, e
	}
	exact, e := memoryExactQuota(operation, strategy, units)
	if e != nil {
		return nil, e
	}
	price, _ := memoryUnitPrice(operation, strategy)
	id := hash([]byte(request.ID + ":" + operation))
	snapshot, _ := json.Marshal(map[string]string{"version": memoryPriceVersion, "operation": operation, "strategy": strategy, "upstream_cny": price, "sale_multiplier": "1.43", "group_multiplier": "1", "quota_per_usd": "500000", "cny_per_usd": "7", "exact_quota": exact.RatString()})
	bill := model.BailianBill{ID: "mem_" + id[:56], UserID: p.User.Id, TokenID: p.Token.Id, ChannelID: ch.Id, Group: p.User.Group, Model: "memory." + operation + "." + strategy, Scope: id, PayloadHash: request.PayloadHash, PriceSnapshot: string(snapshot)}
	charge := MemoryCharge{ID: id, RequestID: request.ID, BillID: bill.ID, UserID: p.User.Id, CloudUserID: request.CloudUserID, Operation: operation, Strategy: strategy, Version: memoryPriceVersion, UpstreamCNY: price, Multiplier: "1.43", ExactQuota: exact.RatString(), State: "reserved", Units: units, CreatedAt: time.Now().Unix()}
	// The wallet hold and its memory accounting row are one durable operation.
	// A crash or failed insert must not leave an unindexed reservation behind.
	e = g.DB.Transaction(func(tx *gorm.DB) error {
		if _, err := model.ReserveBailian(tx, &bill, quotaCeil(exact)); err != nil {
			return err
		}
		if err := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&charge).Error; err != nil {
			return err
		}
		return tx.First(&charge, "id = ?", id).Error // Reuse the original price snapshot.
	})
	if e != nil {
		return nil, e
	}
	return &charge, nil
}

// Wallet -> bill -> fractional remainder in one transaction. A replay advances neither.
func (g *Gateway) settleMemoryCharge(charge *MemoryCharge) error {
	if isHardwareMemory(charge) {
		return g.settleHardwareMemory(charge)
	}
	return g.DB.Transaction(func(tx *gorm.DB) error {
		var user model.User
		if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&user, charge.UserID).Error; e != nil {
			return e
		}
		var bill model.BailianBill
		if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&bill, "id = ?", charge.BillID).Error; e != nil {
			return e
		}
		if bill.State == model.BLSettled || bill.State == model.BLRefunded {
			return nil
		}
		if bill.State != model.BLSubmitted {
			return model.ErrBLConflict
		}
		if e := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&MemoryRemainder{UserID: charge.UserID, ExactQuota: "0"}).Error; e != nil {
			return e
		}
		var carry MemoryRemainder
		if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&carry, "user_id = ?", charge.UserID).Error; e != nil {
			return e
		}
		exact, ok := new(big.Rat).SetString(charge.ExactQuota)
		if !ok {
			return errors.New("invalid_exact_quota")
		}
		fraction, ok := new(big.Rat).SetString(carry.ExactQuota)
		if !ok {
			return errors.New("invalid_carry")
		}
		exact.Add(exact, fraction)
		amount := quotaFloor(exact)
		if e := model.FinishBailian(tx, charge.BillID, amount, false, 0, "memory_upstream_accepted"); e != nil {
			return e
		}
		exact.Sub(exact, new(big.Rat).SetInt64(amount))
		if e := tx.Model(&carry).Update("exact_quota", exact.RatString()).Error; e != nil {
			return e
		}
		return tx.Model(&MemoryCharge{}).Where("id = ?", charge.ID).Update("state", "settled").Error
	})
}
