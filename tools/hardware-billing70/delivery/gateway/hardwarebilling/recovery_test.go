package hardwarebilling

import (
	"errors"
	"gorm.io/gorm"
	"testing"
)

func TestReceiptSurvivesFailedDebitAndRestart(t *testing.T) {
	l := fixture(t)
	if e := l.Recharge(1, "receipt", 100, 100); e != nil {
		t.Fatal(e)
	}
	begin(t, l, "receipt-bill")
	u := Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "official", Units: "1"}
	if e := l.DB.Callback().Update().Before("gorm:update").Register("test:broken-debit", func(tx *gorm.DB) {
		if tx.Statement.Table == "hardware_billing_lot" {
			tx.AddError(errors.New("synthetic debit failure"))
		}
	}); e != nil {
		t.Fatal(e)
	}
	if _, e := l.Settle(1, "receipt-bill", u, "0"); e == nil {
		t.Fatal("failure not exercised")
	}
	var b Bill
	if e := l.DB.First(&b, "id = ?", "receipt-bill").Error; e != nil {
		t.Fatal(e)
	}
	if b.State != "pending" || b.UsageHash == "" || b.SettlementLegacyDebit != "0" {
		t.Fatal("official receipt lost", b.State)
	}
	equal(t, balance(t, l), "90")
	l.DB.Callback().Update().Remove("test:broken-debit")
	restarted := Ledger{DB: l.DB}
	n, e := restarted.RecoverConfirmed(100)
	if e != nil || n != 1 {
		t.Fatal(n, e)
	}
	equal(t, balance(t, l), "94")
	n, e = restarted.RecoverConfirmed(100)
	if e != nil || n != 0 {
		t.Fatal(n, e)
	}
	equal(t, balance(t, l), "94")
}

func TestUnknownReceiptNeverAutoCharges(t *testing.T) {
	l := fixture(t)
	l.Recharge(1, "unknown", 100, 100)
	begin(t, l, "unknown-bill")
	if _, e := l.Settle(1, "unknown-bill", Usage{}, "0"); e != nil {
		t.Fatal(e)
	}
	n, e := l.RecoverConfirmed(100)
	if e != nil || n != 0 {
		t.Fatal(n, e)
	}
	equal(t, balance(t, l), "90")
}
