package bailian

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	glog "gorm.io/gorm/logger"
)

type memoryTestTransport func(*http.Request) (*http.Response, error)
func (fn memoryTestTransport) RoundTrip(r *http.Request) (*http.Response, error) { return fn(r) }

func TestMemoryNativeForwarding(t *testing.T) {
	t.Setenv("BAILIAN_MEMORY_CHANNEL_ID", "2")
	db, err := gorm.Open(sqlite.Open("file:"+uuid.NewString()+"?mode=memory&cache=shared"), &gorm.Config{Logger: glog.Default.LogMode(glog.Silent)})
	if err != nil { t.Fatal(err) }
	sql, _ := db.DB(); defer sql.Close()
	if err = db.AutoMigrate(&model.User{}, &model.Token{}, &model.Channel{}); err != nil { t.Fatal(err) }
	models := "existing-chat-model"
	adminKey, userKey := "memorytestadmin000000000000000001", "memorytestuser0000000000000000002"
	for _, row := range []interface{}{
		&model.User{Id: 1, Username: "admin", Password: "unused", Role: 100, Status: 1, Group: "default", AccessToken: "admin", AffCode: "admin"},
		&model.User{Id: 2, Username: "ordinary", Password: "unused", Role: 1, Status: 1, Group: "default", AccessToken: "ordinary", AffCode: "ordinary"},
		&model.Token{Id: 1, UserId: 1, Key: adminKey, Status: 1, ExpiredTime: -1, Models: &models},
		&model.Token{Id: 2, UserId: 2, Key: userKey, Status: 1, ExpiredTime: -1},
		&model.Channel{Id: 2, Type: 17, Key: "fake-upstream-key", Status: 1, Group: "default"},
	} { if err = db.Create(row).Error; err != nil { t.Fatal(err) } }
	gin.SetMode(gin.TestMode)
	router := gin.New(); NewGateway(context.Background(), db).MemoryRoutes(router)
	prior := memoryClient
	defer func() { memoryClient = prior }()
	calls := 0
	payload := `{"user_id":"connectivity_probe","messages":[{"role":"user","content":"synthetic"}],"plan_version":"lite"}`
	memoryClient = &http.Client{Transport: memoryTestTransport(func(req *http.Request) (*http.Response, error) {
		calls++
		if req.URL.String() != memoryUpstream+"memory_nodes/search" || req.Header.Get("Authorization") != "Bearer fake-upstream-key" { t.Fatal("incorrect upstream") }
		raw, _ := io.ReadAll(req.Body)
		if string(raw) != payload { t.Fatal("native payload was modified") }
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"request_id":"synthetic","memory_nodes":[]}`))}, nil
	})}
	request := func(path, key, origin string) *httptest.ResponseRecorder {
		req := httptest.NewRequest("POST", memoryPrefix+path, strings.NewReader(payload))
		if key != "" { req.Header.Set("Authorization", "Bearer sk-"+key) }
		if origin != "" { req.Header.Set("Origin", origin) }
		rw := httptest.NewRecorder(); router.ServeHTTP(rw, req); return rw
	}
	for _, tc := range []struct{ Path, Key, Origin string; Status int }{
		{"/memory_nodes/search", "", "", 401},
		{"/memory_nodes/search", userKey, "", 403},
		{"/memory_nodes/search", adminKey, "https://browser.invalid", 403},
		{"/unknown", adminKey, "", 404},
		{"/memory_nodes/search", adminKey, "", 200},
	} {
		rw := request(tc.Path, tc.Key, tc.Origin)
		if rw.Code != tc.Status { t.Fatalf("%s: got %d, want %d: %s", tc.Path, rw.Code, tc.Status, rw.Body.String()) }
	}
	if calls != 1 { t.Fatal("unauthorized request reached provider") }
}
