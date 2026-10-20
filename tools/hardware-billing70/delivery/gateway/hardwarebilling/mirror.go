package hardwarebilling

import (
	"gorm.io/gorm"
	"math/big"
)

// This integer is eligibility/display compatibility only; it never determines
// the final money debit. All callers own the exact wallet lock.
func mirrorAvailable(tx *gorm.DB, user int) error {
	if !tx.Migrator().HasTable("users") {
		return nil
	}
	lots, e := loadLots(tx, user)
	if e != nil {
		return e
	}
	sum := new(big.Rat)
	for _, lot := range lots {
		n, e := Parse(string(lot.Remaining))
		if e != nil {
			return e
		}
		sum.Add(sum, n)
	}
	sum.Mul(sum, big.NewRat(500, 1))
	q := new(big.Int).Quo(sum.Num(), sum.Denom())
	if new(big.Int).Mod(sum.Num(), sum.Denom()).Sign() != 0 {
		q.Add(q, big.NewInt(1))
	}
	if !q.IsInt64() {
		return gorm.ErrInvalidData
	}
	return tx.Table("users").Where("id = ?", user).Update("quota", q.Int64()).Error
}
