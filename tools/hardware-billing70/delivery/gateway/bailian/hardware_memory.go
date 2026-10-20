package bailian

import (
	"errors"
	"github.com/songquanpeng/one-api/hardwarebilling"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm"
	"math/big"
	"os"
	"strconv"
	"strings"
	"time"
)

const hardwareMemoryVersion = "aliyun-memory-20261001-margin70-v1"

func isHardwareMemory(c *MemoryCharge) bool { return c.Version == hardwareMemoryVersion }

func (g *Gateway) reserveHardwareMemory(p Principal, request *MemoryRequest, operation, strategy string, units int64) (*MemoryCharge, bool, error) {
	if os.Getenv("HW_BILLING_ENABLED") != "1" {
		return nil, false, nil
	}
	var wallet hardwarebilling.Wallet
	e := g.DB.First(&wallet, "user_id = ?", p.User.Id).Error
	if errors.Is(e, gorm.ErrRecordNotFound) {
		return nil, false, nil
	}
	if e != nil {
		return nil, true, e
	}
	var actor MemoryEntity
	if e = g.DB.First(&actor, "cloud_user_id = ? AND user_id = ?", request.CloudUserID, p.User.Id).Error; e != nil {
		return nil, true, e
	}
	if actor.ProductAccount != wallet.ProductAccount || wallet.State != "enabled" {
		return nil, true, errors.New("hardware_memory_account_mismatch")
	}
	name, ok := map[string]string{"fact": "fact_add", "portrait": "portrait_add", "search": "search", "storage": "storage_item_hour"}[operation]
	if !ok {
		return nil, true, errors.New("hardware_memory_operation_unverified")
	}
	price, e := hardwarebilling.MemoryPrice(name, strategy)
	if e != nil {
		return nil, true, e
	}
	u := hardwarebilling.Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "reservation-only", Units: hardwarebilling.Exact(strconv.FormatInt(units, 10))}
	cost, e := price.Cost(u)
	if e != nil {
		return nil, true, e
	}
	sale, e := hardwarebilling.SaleCNY(cost)
	if e != nil {
		return nil, true, e
	}
	old, e := memoryExactQuota(operation, strategy, units)
	if e != nil {
		return nil, true, e
	}
	legacy := hardwarebilling.Exact(new(big.Rat).Quo(old, big.NewRat(500, 1)).RatString())
	id := hash([]byte(request.ID + ":" + operation))
	upstream, _ := memoryUnitPrice(operation, strategy)
	c := MemoryCharge{ID: id, RequestID: request.ID, BillID: "hw_mem_" + id[:56], UserID: p.User.Id, CloudUserID: request.CloudUserID, Operation: operation, Strategy: strategy, Version: hardwareMemoryVersion, UpstreamCNY: upstream, Multiplier: "10/3", ExactQuota: old.RatString(), State: "reserved", Units: units, CreatedAt: time.Now().Unix()}
	// Storage is actual retained usage, even with no remaining funds. A zero hold
	// records the evidence and Settle persists outstanding debt instead of hiding it.
	if operation == "storage" {
		sale = "0"
		legacy = "0"
	}
	e = g.DB.Transaction(func(tx *gorm.DB) error {
		l := hardwarebilling.Ledger{DB: tx}
		b, e := l.Begin(p.User.Id, c.BillID, request.PayloadHash, price, sale, legacy)
		if e != nil {
			return e
		}
		if b.Replay {
			return tx.First(&c, "id = ?", id).Error
		}
		return tx.Create(&c).Error
	})
	return &c, true, e
}

func (g *Gateway) settleHardwareMemory(c *MemoryCharge) error {
	return g.DB.Transaction(func(tx *gorm.DB) error {
		evidence := ""
		if c.Operation == "storage" {
			var s MemoryStorageHour
			if e := tx.First(&s, "id = ?", c.RequestID).Error; e != nil {
				return e
			}
			evidence = s.EvidenceRequestID
		} else {
			var r MemoryRequest
			if e := tx.First(&r, "id = ? AND user_id = ?", c.RequestID, c.UserID).Error; e != nil {
				return e
			}
			if r.State != "complete" || r.Status < 200 || r.Status >= 300 {
				return errors.New("memory_acceptance_not_confirmed")
			}
			evidence = r.RequestID
		}
		u := hardwarebilling.Usage{Confirmed: evidence != "", Source: "upstream", UpstreamRequestID: evidence, Units: hardwarebilling.Exact(strconv.FormatInt(c.Units, 10))}
		old, e := hardwarebilling.Parse(c.ExactQuota)
		if e != nil {
			return e
		}
		old.Quo(old, big.NewRat(500, 1))
		b, e := (hardwarebilling.Ledger{DB: tx}).Settle(c.UserID, c.BillID, u, hardwarebilling.Exact(old.RatString()))
		if e != nil {
			return e
		}
		if b.State != "settled" {
			if e := tx.Model(c).Update("state", b.State).Error; e != nil {
				return e
			}
			return nil
		}
		return tx.Model(c).Update("state", "settled").Error
	})
}

func claimMemorySubmit(tx *gorm.DB, c *MemoryCharge) (bool, error) {
	if !isHardwareMemory(c) {
		return model.ClaimSubmitBailian(tx, c.BillID)
	}
	result := tx.Model(&MemoryCharge{}).Where("id = ? AND state = ?", c.ID, "reserved").Update("state", "submitted")
	return result.RowsAffected == 1, result.Error
}
func (g *Gateway) releaseMemoryCharge(c *MemoryCharge, reason string) error {
	if !isHardwareMemory(c) {
		return model.FinishBailian(g.DB, c.BillID, 0, false, 0, reason)
	}
	return (hardwarebilling.Ledger{DB: g.DB}).Refund(c.UserID, c.BillID, "release:"+c.ID)
}
func (g *Gateway) markMemoryUnknown(c *MemoryCharge) error {
	if !isHardwareMemory(c) {
		return model.FinishBailian(g.DB, c.BillID, 0, true, 0, "memory_result_unknown")
	}
	_, e := (hardwarebilling.Ledger{DB: g.DB}).Settle(c.UserID, c.BillID, hardwarebilling.Usage{Source: "upstream"}, "0")
	return e
}

func memoryResponsePrice(charges []*MemoryCharge) string {
	for _, c := range charges {
		if strings.HasPrefix(c.Version, "aliyun-memory-20261001-margin70") {
			return hardwareMemoryVersion
		}
	}
	return memoryPriceVersion
}
