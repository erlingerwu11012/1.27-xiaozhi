package hardwarebilling

import (
	"fmt"
	mysqlcfg "github.com/go-sql-driver/mysql"
	"gorm.io/driver/mysql"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
	"os"
	"strings"
	"sync"
	"testing"
)

func TestMySQLConcurrentBillsAndRecharge(t *testing.T) {
	name := os.Getenv("HW_BILLING_TEST_DATABASE")
	if name == "" {
		t.Skip("isolated MySQL not configured")
	}
	if !strings.HasPrefix(name, "hardware_billing_test_") || strings.ContainsAny(name, " ;/'\"`") {
		t.Fatal("unsafe test database")
	}
	cfg := mysqlcfg.NewConfig()
	cfg.User = "root"
	cfg.Passwd = os.Getenv("HW_BILLING_TEST_PASSWORD")
	cfg.Net = "tcp"
	cfg.Addr = "127.0.0.1:3306"
	cfg.DBName = name
	db, e := gorm.Open(mysql.Open(cfg.FormatDSN()), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
	if e != nil {
		t.Fatal("test database connection failed")
	}
	l := Ledger{db}
	if e := l.Migrate(); e != nil {
		t.Fatal(e)
	}
	if e := l.Bootstrap(70001, "99070001", 0); e != nil {
		t.Fatal(e)
	}
	var wg sync.WaitGroup
	errs := make(chan error, 80)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); errs <- l.Recharge(70001, "synthetic-order", 10000, 10000) }()
	}
	wg.Wait()
	p, _ := MemoryLite("fact_add")
	u := Usage{Confirmed: true, Source: "upstream", UpstreamRequestID: "synthetic-event", Units: "1"}
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			id := fmt.Sprintf("mysql-synthetic-%d", i)
			_, e := l.Begin(70001, id, hash([]byte(id)), p, "0.1", "0")
			if e != nil {
				errs <- e
				return
			}
			_, e = l.Settle(70001, id, u, "0")
			errs <- e
			_, e = l.Settle(70001, id, u, "0")
			errs <- e
		}(i)
	}
	wg.Wait()
	close(errs)
	for e := range errs {
		if e != nil {
			t.Fatal(e)
		}
	}
	lots, e := loadLots(db, 70001)
	if e != nil {
		t.Fatal(e)
	}
	sum := zero()
	for _, lot := range lots {
		r, e := Parse(string(lot.Remaining))
		if e != nil {
			t.Fatal(e)
		}
		sum.Add(sum, r)
	}
	equal(t, exact(sum), "9880")
	var bills int64
	db.Model(&Bill{}).Where("user_id = ? AND state = ?", 70001, "settled").Count(&bills)
	if bills != 20 {
		t.Fatal(bills)
	}
	var recharges int64
	db.Model(&StoredLot{}).Where("user_id = ? AND kind = ?", 70001, "paid").Count(&recharges)
	if recharges != 1 {
		t.Fatal(recharges)
	}
}
