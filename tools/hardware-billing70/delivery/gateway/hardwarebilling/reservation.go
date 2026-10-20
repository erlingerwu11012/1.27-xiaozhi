package hardwarebilling

import (
	"encoding/json"
	"errors"
	"gorm.io/gorm"
)

// ResizeReservation only updates an estimated hold. No final usage or cost is
// written until Settle receives confirmed upstream evidence.
func (l Ledger) ResizeReservation(user int, id string, sale, legacy Exact) error {
	return l.DB.Transaction(func(tx *gorm.DB) error {
		if e := lockedWallet(tx, user); e != nil {
			return e
		}
		var b Bill
		if e := tx.First(&b, "id = ? AND user_id = ?", id, user).Error; e != nil {
			return e
		}
		if b.State != "reserved" || b.UsageJSON != "" {
			return errors.New("reservation_not_open")
		}
		var held []Allocation
		if e := json.Unmarshal([]byte(b.Allocations), &held); e != nil {
			return e
		}
		if e := alter(tx, user, held, true); e != nil {
			return e
		}
		lots, e := loadLots(tx, user)
		if e != nil {
			return e
		}
		alloc, e := Allocate(lots, sale, legacy)
		if e != nil {
			return e
		}
		if e := alter(tx, user, alloc, false); e != nil {
			return e
		}
		raw, e := json.Marshal(alloc)
		if e != nil {
			return e
		}
		return tx.Model(&b).Updates(map[string]interface{}{"allocations": string(raw), "reservation_json": string(raw)}).Error
	})
}
