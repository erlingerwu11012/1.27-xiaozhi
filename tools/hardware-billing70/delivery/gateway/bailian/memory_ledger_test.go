package bailian

import (
	"context"
	"github.com/google/uuid"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	glog "gorm.io/gorm/logger"
	"math/big"
	"testing"
)

func TestMemorySalePrices(t *testing.T) {
	for _, tc := range []struct {
		op, plan, want string
		units          int64
	}{
		{"fact", "lite", "12870/7", 1}, {"portrait", "lite", "17875/7", 1},
		{"search", "lite", "143/70", 1}, {"storage", "lite", "143/7000", 1},
		{"fact", "pro", "21450/7", 1}, {"search", "pro", "715/7", 1},
		{"storage", "lite", "1430/7", 10000},
	} {
		got, e := memoryExactQuota(tc.op, tc.plan, tc.units)
		if e != nil || got.RatString() != tc.want {
			t.Fatalf("%s/%s: %v %v, want %s", tc.op, tc.plan, got, e, tc.want)
		}
	}
}
func TestMemoryAttestationIsBoundToOwnerPersonAndGeneration(t *testing.T) {
	original := memoryAttestation("synthetic-secret-only", 7, "10", "usr_a", "1", "100")
	for _, other := range []string{
		memoryAttestation("synthetic-secret-only", 8, "10", "usr_a", "1", "100"),
		memoryAttestation("synthetic-secret-only", 7, "11", "usr_a", "1", "100"),
		memoryAttestation("synthetic-secret-only", 7, "10", "usr_b", "1", "100"),
		memoryAttestation("synthetic-secret-only", 7, "10", "usr_a", "2", "100"),
	} {
		if original == other {
			t.Fatal("attestation not bound")
		}
	}
}
func TestMemoryFractionalCarryAndSettlementReplay(t *testing.T) {
	db, e := gorm.Open(sqlite.Open("file:"+uuid.NewString()+"?mode=memory&cache=shared"), &gorm.Config{Logger: glog.Default.LogMode(glog.Silent)})
	if e != nil {
		t.Fatal(e)
	}
	sql, _ := db.DB()
	defer sql.Close()
	for _, migration := range []func(*gorm.DB) error{
		func(db *gorm.DB) error {
			return db.AutoMigrate(&model.User{}, &model.Token{}, &model.Channel{}, &model.Log{})
		},
		model.MigrateBailianLedger, MigrateMemoryProduct,
	} {
		if e = migration(db); e != nil {
			t.Fatal(e)
		}
	}
	for _, row := range []interface{}{
		&model.User{Id: 1, Username: "memory-test", Password: "unused", Status: 1, Group: "default", Quota: 1000, AccessToken: "test", AffCode: "test"},
		&model.Token{Id: 1, UserId: 1, Key: "synthetic", Status: 1, ExpiredTime: -1, RemainQuota: 1000},
		&model.Channel{Id: 2, Type: 17, Key: "synthetic", Status: 1, Group: "default"},
	} {
		if e = db.Create(row).Error; e != nil {
			t.Fatal(e)
		}
	}
	var p Principal
	db.First(&p.User, 1)
	db.First(&p.Token, 1)
	g := NewGateway(context.Background(), db)
	ch := model.Channel{Id: 2}
	for i := 0; i < 70; i++ {
		request := MemoryRequest{ID: hash([]byte(uuid.NewString())), PayloadHash: hash([]byte("synthetic")), CloudUserID: "synthetic-person"}
		charge, e := g.reserveMemoryCharge(p, ch, &request, "search", "lite", 1)
		if e != nil {
			t.Fatal(e)
		}
		if e = model.SubmitBailian(db, charge.BillID); e != nil {
			t.Fatal(e)
		}
		if e = g.settleMemoryCharge(charge); e != nil {
			t.Fatal(e)
		}
		if e = g.settleMemoryCharge(charge); e != nil {
			t.Fatal(e)
		}
	}
	var user model.User
	db.First(&user, 1)
	if user.Quota != 857 || user.UsedQuota != 143 {
		t.Fatalf("rounded or duplicate charge: balance=%d used=%d", user.Quota, user.UsedQuota)
	}
	var carry MemoryRemainder
	db.First(&carry, 1)
	remainder, _ := new(big.Rat).SetString(carry.ExactQuota)
	if remainder.Sign() != 0 {
		t.Fatal("fraction should return to zero")
	}
}
