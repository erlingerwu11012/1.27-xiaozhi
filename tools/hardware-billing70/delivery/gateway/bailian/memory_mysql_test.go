package bailian

import (
	"context"
	"fmt"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/driver/mysql"
	"gorm.io/gorm"
	glog "gorm.io/gorm/logger"
	"os"
	"strings"
	"sync"
	"testing"
)

func TestMemoryMySQLConcurrentWalletPrecision(t *testing.T) {
	database := os.Getenv("MEMORY_MYSQL_TEST_DATABASE")
	if database == "" {
		t.Skip("isolated MySQL fixture required")
	}
	if !strings.HasPrefix(database, "bailian_memory_wallet_test_") {
		t.Fatal("unsafe test database")
	}
	for _, c := range database {
		if c != '_' && !(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') {
			t.Fatal("invalid database")
		}
	}
	dsn := "root:" + os.Getenv("MEMORY_MYSQL_TEST_PASSWORD") + "@tcp(127.0.0.1:3306)/" + database + "?charset=utf8mb4&parseTime=True&loc=Local"
	db, e := gorm.Open(mysql.Open(dsn), &gorm.Config{Logger: glog.Default.LogMode(glog.Silent)})
	if e != nil {
		t.Fatal("test database connection failed")
	}
	sql, _ := db.DB()
	defer sql.Close()
	sql.SetMaxOpenConns(8)
	for _, models := range [][]interface{}{{&model.User{}, &model.Token{}, &model.Channel{}, &model.Log{}}} {
		if e = db.AutoMigrate(models...); e != nil {
			t.Fatal(e)
		}
	}
	if e = model.MigrateBailianLedger(db); e != nil {
		t.Fatal(e)
	}
	if e = MigrateMemoryProduct(db); e != nil {
		t.Fatal(e)
	}
	p := Principal{User: model.User{Id: 1, Username: "synthetic", Group: "default", Status: 1, Quota: 10000, AccessToken: "synthetic", AffCode: "synthetic"}, Token: model.Token{Id: 1, UserId: 1, Key: "synthetic", Status: 1, ExpiredTime: -1, RemainQuota: 10000}}
	db.Create(&p.User)
	db.Create(&p.Token)
	db.Create(&model.User{Id: 2, Username: "other", Group: "default", Status: 1, Quota: 10000, AccessToken: "other", AffCode: "other"})
	g := NewGateway(context.Background(), db)
	var wait sync.WaitGroup
	failures := make(chan error, 50)
	for i := 0; i < 50; i++ {
		wait.Add(1)
		go func(index int) {
			defer wait.Done()
			request := MemoryRequest{ID: hash([]byte(fmt.Sprint(index))), UserID: 1, CloudUserID: "synthetic-person", PayloadHash: hash([]byte("synthetic"))}
			charge, e := g.reserveMemoryCharge(p, model.Channel{Id: 2}, &request, "search", "lite", 1)
			if e == nil {
				e = model.SubmitBailian(db, charge.BillID)
			}
			if e == nil {
				e = g.settleMemoryCharge(charge)
			}
			if e == nil {
				e = g.settleMemoryCharge(charge)
			}
			if e != nil {
				failures <- e
			}
		}(i)
	}
	wait.Wait()
	close(failures)
	for e := range failures {
		t.Fatal(e)
	}
	var user model.User
	db.First(&user, 1)
	if user.UsedQuota != 102 || user.Quota != 9898 {
		t.Fatal("concurrent price/rounding mismatch", user.UsedQuota, user.Quota)
	}
	var other model.User
	db.First(&other, 2)
	if other.Quota != 10000 {
		t.Fatal("foreign wallet changed")
	}
	var carry MemoryRemainder
	db.First(&carry, 1)
	if carry.ExactQuota != "1/7" {
		t.Fatal("wrong accumulated fraction", carry.ExactQuota)
	}
}
