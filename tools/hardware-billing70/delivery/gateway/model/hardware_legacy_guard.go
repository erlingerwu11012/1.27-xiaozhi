package model

import (
	"errors"
	"gorm.io/gorm"
)

// Old ambiguous bills retain their holds after cutover. Their legacy operators
// must not mutate the old quota underneath an independently authoritative wallet.
// Reconciliation requires an explicit future bridge with verified receipts.
func guardMigratedLegacyWallet(tx *gorm.DB, user int) error {
	if !tx.Migrator().HasTable("hardware_billing_wallet") {
		return nil
	}
	var n int64
	if e := tx.Table("hardware_billing_wallet").Where("user_id = ?", user).Count(&n).Error; e != nil {
		return e
	}
	if n > 0 {
		return errors.New("legacy_bill_requires_migrated_wallet_reconciliation")
	}
	return nil
}

// Presence, not the coarse integer mirror, selects the authoritative wallet.
func HasHardwareWallet(tx *gorm.DB, user int) (bool, error) {
	if !tx.Migrator().HasTable("hardware_billing_wallet") {
		return false, nil
	}
	var n int64
	e := tx.Table("hardware_billing_wallet").Where("user_id = ?", user).Count(&n).Error
	return n > 0, e
}
