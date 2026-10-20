package bailian

import (
	"github.com/songquanpeng/one-api/hardwarebilling"
	"github.com/songquanpeng/one-api/model"
	"testing"
)

func TestHardwareMemoryActualReceiptReplayAndUnknownRecovery(t *testing.T) {
	t.Setenv("HW_BILLING_ENABLED", "1")
	g, db := memoryFixture(t, 100000)
	l := hardwarebilling.Ledger{DB: db}
	if e := l.Migrate(); e != nil {
		t.Fatal(e)
	}
	if e := l.Bootstrap(1, "99100001", 0); e != nil {
		t.Fatal(e)
	}
	if e := l.Recharge(1, "memory", 100, 100); e != nil {
		t.Fatal(e)
	}
	actor := MemoryEntity{CloudUserID: "synthetic-person", UserID: 1, ProductAccount: "99100001", PersonID: "member", State: "active"}
	db.Create(&actor)
	var p Principal
	db.First(&p.User, 1)
	db.First(&p.Token, 1)
	req := MemoryRequest{ID: hash([]byte("request")), UserID: 1, CloudUserID: actor.CloudUserID, PayloadHash: hash([]byte("payload")), State: "prepared"}
	db.Create(&req)
	c, e := g.reserveMemoryCharge(p, model.Channel{Id: 2}, &req, "fact", "lite", 1)
	if e != nil || !isHardwareMemory(c) {
		t.Fatal(c, e)
	}
	if e := g.markMemoryUnknown(c); e != nil {
		t.Fatal(e)
	}
	var bill hardwarebilling.Bill
	db.First(&bill, "id = ?", c.BillID)
	if bill.State != "pending" || bill.CostCNY != "" {
		t.Fatal(bill)
	}
	db.Model(&req).Updates(map[string]interface{}{"state": "complete", "status": 200, "request_id": "ali-real-receipt"})
	if e := g.settleMemoryCharge(c); e != nil {
		t.Fatal(e)
	}
	if e := g.settleMemoryCharge(c); e != nil {
		t.Fatal(e)
	}
	db.First(&bill, "id = ?", c.BillID)
	if bill.CostCNY != "9/500" || bill.SaleCNY != "3/50" || bill.State != "settled" {
		t.Fatal(bill)
	}
	var lot hardwarebilling.StoredLot
	db.Where("kind = ?", "paid").First(&lot)
	if lot.Remaining != "94" {
		t.Fatal(lot)
	}
	var old int64
	db.Model(&model.BailianBill{}).Count(&old)
	if old != 0 {
		t.Fatal("double ledger")
	}
	db.Model(&actor).Update("product_account", "another")
	if _, _, e := g.reserveHardwareMemory(p, &req, "search", "lite", 1); e == nil {
		t.Fatal("wrong account")
	}
}

func TestHardwareMemoryStorageDebtIsRetainedAndRechargeSettlesOnce(t *testing.T) {
	t.Setenv("HW_BILLING_ENABLED", "1")
	g, db := memoryFixture(t, 0)
	l := hardwarebilling.Ledger{DB: db}
	if e := l.Migrate(); e != nil {
		t.Fatal(e)
	}
	if e := l.Bootstrap(1, "99100001", 0); e != nil {
		t.Fatal(e)
	}
	entity := MemoryEntity{CloudUserID: "storage-person", UserID: 1, TokenID: 1, ProductAccount: "99100001", State: "active"}
	db.Create(&entity)
	sample := MemoryStorageHour{ID: hash([]byte("hour")), CloudUserID: entity.CloudUserID, UserID: 1, TokenID: 1, ChannelID: 2, Hour: 1, FactCount: 10000, State: "pending", ExactQuota: "1", EvidenceRequestID: "ali-count-receipt"}
	db.Create(&sample)
	if e := g.settleMemoryStorageDebt(); e != nil {
		t.Fatal(e)
	}
	db.First(&sample, "id = ?", sample.ID)
	if sample.State != "debt" {
		t.Fatal(sample)
	}
	var bill hardwarebilling.Bill
	db.First(&bill)
	if bill.State != "outstanding" || bill.CostCNY != "1/500" {
		t.Fatal(bill)
	}
	if e := l.Recharge(1, "storage", 100, 100); e != nil {
		t.Fatal(e)
	}
	if e := g.settleMemoryStorageDebt(); e != nil {
		t.Fatal(e)
	}
	if e := g.settleMemoryStorageDebt(); e != nil {
		t.Fatal(e)
	}
	db.First(&sample, "id = ?", sample.ID)
	if sample.State != "settled" {
		t.Fatal(sample)
	}
	var total int64
	db.Model(&hardwarebilling.Bill{}).Count(&total)
	if total != 1 {
		t.Fatal(total)
	}
}

func TestMigratedWalletCannotBeMutatedByOldBilling(t *testing.T) {
	_, db := memoryFixture(t, 100000)
	old := model.BailianBill{ID: "legacy-ambiguous", UserID: 1, TokenID: 1, Model: "qwen-audio-3.0-tts-plus", State: model.BLReview, Held: 500, Scope: hash([]byte("old")), PayloadHash: hash([]byte("old"))}
	if e := db.Create(&old).Error; e != nil {
		t.Fatal(e)
	}
	l := hardwarebilling.Ledger{DB: db}
	if e := l.Migrate(); e != nil {
		t.Fatal(e)
	}
	if e := l.Bootstrap(1, "99100001", 100000); e != nil {
		t.Fatal(e)
	}
	var before model.User
	db.First(&before, 1)
	if e := model.FinishBailian(db, old.ID, 0, false, 0, "unknown"); e == nil {
		t.Fatal("old settlement bypassed migrated wallet")
	}
	req := model.BailianBill{ID: "old-new", UserID: 1, TokenID: 1, Model: old.Model, Scope: hash([]byte("new")), PayloadHash: hash([]byte("new"))}
	if _, e := model.ReserveBailian(db, &req, 500); e == nil {
		t.Fatal("old reserve bypassed migrated wallet")
	}
	var after model.User
	db.First(&after, 1)
	if after.Quota != before.Quota || after.UsedQuota != before.UsedQuota {
		t.Fatal("legacy balance changed")
	}
}
