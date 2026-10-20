package hardwarebilling

import "testing"

func TestBootstrapDoesNotOverwriteExistingBalance(t *testing.T) {
	l := fixture(t)
	if e := l.Bootstrap(2, "synthetic2", 505); e != nil {
		t.Fatal(e)
	}
	if e := l.Bootstrap(2, "synthetic2", 999999); e != nil {
		t.Fatal(e)
	}
	var lot StoredLot
	if e := l.DB.First(&lot, "user_id = ?", 2).Error; e != nil {
		t.Fatal(e)
	}
	equal(t, Exact(lot.Remaining), "1.01")
	if e := l.Bootstrap(2, "different", 505); e == nil {
		t.Fatal("binding reassigned")
	}
}
func TestGiftsKeepUnknownCashValue(t *testing.T) {
	l := fixture(t)
	if e := l.GrantLegacy(1, "grant1", "10"); e != nil {
		t.Fatal(e)
	}
	if e := l.GrantLegacy(1, "grant1", "10"); e != nil {
		t.Fatal(e)
	}
	if e := l.GrantLegacy(1, "grant1", "11"); e == nil {
		t.Fatal("gift amount changed on retry")
	}
	var n int64
	l.DB.Model(&StoredLot{}).Count(&n)
	if n != 1 {
		t.Fatal(n)
	}
	var lot StoredLot
	l.DB.First(&lot, "user_id = ?", 1)
	if lot.CNYPerPoint != "0" || lot.Kind != "legacy" {
		t.Fatal("gift treated as paid")
	}
}
