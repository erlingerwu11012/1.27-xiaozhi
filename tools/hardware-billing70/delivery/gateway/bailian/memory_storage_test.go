package bailian

import (
	"context"
	"github.com/google/uuid"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	glog "gorm.io/gorm/logger"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

func memoryFixture(t *testing.T, quota int) (*Gateway, *gorm.DB) {
	t.Helper()
	db, e := gorm.Open(sqlite.Open("file:"+uuid.NewString()+"?mode=memory&cache=shared"), &gorm.Config{Logger: glog.Default.LogMode(glog.Silent)})
	if e != nil {
		t.Fatal(e)
	}
	sql, _ := db.DB()
	t.Cleanup(func() { sql.Close() })
	if e = db.AutoMigrate(&model.User{}, &model.Token{}, &model.Channel{}, &model.Log{}); e != nil {
		t.Fatal(e)
	}
	if e = model.MigrateBailianLedger(db); e != nil {
		t.Fatal(e)
	}
	if e = MigrateMemoryProduct(db); e != nil {
		t.Fatal(e)
	}
	for _, row := range []interface{}{
		&model.User{Id: 1, Username: "memory-storage-test", Password: "unused", Status: 1, Group: "default", Quota: int64(quota), AccessToken: "test", AffCode: "test"},
		&model.Token{Id: 1, UserId: 1, Key: "synthetic", Status: 1, ExpiredTime: -1, RemainQuota: int64(quota)},
		&model.Channel{Id: 2, Type: 17, Key: "synthetic", Status: 1, Group: "default"},
	} {
		if e = db.Create(row).Error; e != nil {
			t.Fatal(e)
		}
	}
	return NewGateway(context.Background(), db), db
}

func TestMemoryStorageDebtRechargeReplayAndActualDelete(t *testing.T) {
	t.Setenv("BAILIAN_MEMORY_CHANNEL_ID", "2")
	t.Setenv("BAILIAN_MEMORY_STORAGE_COUNT_VERIFIED", "1")
	gateway, db := memoryFixture(t, 0)
	entity := MemoryEntity{CloudUserID: "storage-person", UserID: 1, TokenID: 1, ProductAccount: "10", PersonID: "usr_a", State: "active"}
	if e := db.Create(&entity).Error; e != nil {
		t.Fatal(e)
	}
	prior := memoryClient
	t.Cleanup(func() { memoryClient = prior })
	count := 10000
	calls := 0
	memoryClient = &http.Client{Transport: memoryTestTransport(func(request *http.Request) (*http.Response, error) {
		calls++
		if request.URL.Query().Get("user_id") != entity.CloudUserID {
			t.Fatal("wrong person count")
		}
		raw := `{"total":10000,"request_id":"count-evidence","memory_nodes":[]}`
		if count == 0 {
			raw = `{"total":0,"request_id":"deleted-count-evidence","memory_nodes":[]}`
		}
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(raw))}, nil
	})}
	now := time.Unix(1800000000, 0)
	if e := gateway.collectMemoryStorage(context.Background(), now); e != nil {
		t.Fatal(e)
	}
	if e := gateway.collectMemoryStorage(context.Background(), now.Add(time.Minute)); e != nil {
		t.Fatal(e)
	}
	var sample MemoryStorageHour
	db.First(&sample)
	if sample.State != "debt" || sample.FactCount != 10000 || calls != 1 {
		t.Fatalf("invalid debt/dedup: %#v calls=%d", sample, calls)
	}
	db.Model(&model.User{}).Where("id = 1").Update("quota", 1000)
	db.Model(&model.Token{}).Where("id = 1").Update("remain_quota", 1000)
	if e := gateway.settleMemoryStorageDebt(); e != nil {
		t.Fatal(e)
	}
	if e := gateway.settleMemoryStorageDebt(); e != nil {
		t.Fatal(e)
	}
	var user model.User
	db.First(&user, 1)
	if user.Quota != 796 || user.UsedQuota != 204 {
		t.Fatalf("debt charged wrong amount: %d / %d", user.Quota, user.UsedQuota)
	}
	db.First(&sample, "id = ?", sample.ID)
	if sample.State != "settled" || sample.BillID == "" {
		t.Fatal("missing storage bill")
	}
	db.Model(&entity).Updates(map[string]interface{}{"state": "retired", "cleanup_confirmed": true})
	count = 0
	if e := gateway.collectMemoryStorage(context.Background(), now.Add(time.Hour)); e != nil {
		t.Fatal(e)
	}
	db.First(&entity, "cloud_user_id = ?", entity.CloudUserID)
	if entity.State != "deleted" {
		t.Fatal("actual empty count and cleanup did not stop storage")
	}
	if e := gateway.collectMemoryStorage(context.Background(), now.Add(2*time.Hour)); e != nil {
		t.Fatal(e)
	}
	if calls != 2 {
		t.Fatal("deleted entity still sampled")
	}
	db.First(&user, 1)
	if user.Quota != 796 {
		t.Fatal("zero count charged")
	}
}

func TestMemoryStorageNeverInventsCountOrDeletesBeforeLateAdd(t *testing.T) {
	t.Setenv("BAILIAN_MEMORY_CHANNEL_ID", "2")
	t.Setenv("BAILIAN_MEMORY_STORAGE_COUNT_VERIFIED", "1")
	gateway, db := memoryFixture(t, 1000)
	entity := MemoryEntity{CloudUserID: "storage-pending", UserID: 1, TokenID: 1, State: "retired", CleanupConfirmed: true}
	db.Create(&entity)
	db.Create(&MemoryRequest{ID: "late-add", CloudUserID: entity.CloudUserID, Path: "add-async", State: "review"})
	prior := memoryClient
	t.Cleanup(func() { memoryClient = prior })
	valid := false
	memoryClient = &http.Client{Transport: memoryTestTransport(func(*http.Request) (*http.Response, error) {
		raw := `{"request_id":"no-count","memory_nodes":[]}`
		if valid {
			raw = `{"request_id":"verified-zero","total":0,"memory_nodes":[]}`
		}
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(raw))}, nil
	})}
	now := time.Unix(1800000000, 0)
	if err := gateway.collectMemoryStorage(context.Background(), now); err == nil {
		t.Fatal("sampling failure was hidden")
	}
	var samples int64
	db.Model(&MemoryStorageHour{}).Count(&samples)
	if samples != 0 {
		t.Fatal("missing count treated as zero")
	}
	valid = true
	gateway.collectMemoryStorage(context.Background(), now)
	db.First(&entity, "cloud_user_id = ?", entity.CloudUserID)
	if entity.State != "retired" {
		t.Fatal("late add could resurrect a deleted entity")
	}
}
