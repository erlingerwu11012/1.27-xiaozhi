package bailian

import (
	"encoding/json"
	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/model"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestMemoryManualReviewIsAuditedExactAndIdempotent(t *testing.T) {
	for _, outcome := range []string{"accepted", "rejected"} {
		t.Run(outcome, func(t *testing.T) {
			g, db := memoryFixture(t, 10000)
			key := "syntheticadminmemoryreviewtoken"
			db.Model(&model.Token{}).Where("id = 1").Update("key", key)
			var p Principal
			db.First(&p.User, 1)
			db.First(&p.Token, 1)
			req := MemoryRequest{ID: strings.Repeat("a", 64), CloudUserID: "review_person", UserID: 1, PayloadHash: hash([]byte("synthetic")), Path: "add-async", State: "submitted"}
			db.Create(&req)
			charge, e := g.reserveMemoryCharge(p, model.Channel{Id: 2}, &req, "fact", "lite", 1)
			if e != nil {
				t.Fatal(e)
			}
			model.SubmitBailian(db, charge.BillID)
			g.memoryUnknown(&req, []*MemoryCharge{charge})
			router := gin.New()
			g.Routes(router)
			payload, _ := json.Marshal(map[string]interface{}{"operation_id": "review-operation-1", "outcome": outcome, "reason": "official support confirmation", "evidence": "synthetic official request outcome", "result": map[string]interface{}{"event_id": "verified_event", "request_id": "verified_request", "user_id": req.CloudUserID}})
			call := func() *httptest.ResponseRecorder {
				request := httptest.NewRequest("POST", "/bailian/v1/memory/operations/"+req.ID+"/admin-resolve", strings.NewReader(string(payload)))
				request.Header.Set("Authorization", "Bearer sk-"+key)
				out := httptest.NewRecorder()
				router.ServeHTTP(out, request)
				return out
			}
			if out := call(); out.Code != 403 {
				t.Fatal("ordinary token accepted", out.Code)
			}
			db.Model(&model.User{}).Where("id = 1").Update("role", model.RoleAdminUser)
			for i := 0; i < 2; i++ {
				if out := call(); out.Code != 200 {
					t.Fatal(out.Code, out.Body.String())
				}
			}
			var user model.User
			db.First(&user, 1)
			db.First(&req, "id = ?", req.ID)
			if outcome == "accepted" {
				if user.UsedQuota != 1838 || req.State != "complete" {
					t.Fatal("incorrect exact settlement", user.UsedQuota, req.State)
				}
			} else if user.UsedQuota != 0 || user.Quota != 10000 || req.State != "rejected" {
				t.Fatal("refund failed", user.UsedQuota, user.Quota, req.State)
			}
			var count int64
			db.Model(&MemoryResolution{}).Count(&count)
			if count != 1 {
				t.Fatal("duplicate audit", count)
			}
		})
	}
}
