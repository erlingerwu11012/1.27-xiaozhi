package bailian

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

func memoryAttestation(secret string, owner int, account, person, generation, expires string) string {
	canonical := strings.Join([]string{"memory-v1", strconv.Itoa(owner), account, person, generation, expires}, "\n")
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(canonical))
	return hex.EncodeToString(mac.Sum(nil))
}
func authorizeMemoryActor(c *gin.Context, p Principal) (MemoryEntity, error) {
	account := c.GetHeader("X-Memory-Account")
	person := c.GetHeader("X-Memory-Person")
	generation := c.GetHeader("X-Memory-Generation")
	expires := c.GetHeader("X-Memory-Expires")
	secret := os.Getenv("BAILIAN_MEMORY_SERVICE_SECRET")
	expiry, e := strconv.ParseInt(expires, 10, 64)
	gen, e2 := strconv.ParseInt(generation, 10, 64)
	accountNumber, e3 := strconv.ParseInt(account, 10, 64)
	if len(secret) < 32 || e != nil || e2 != nil || e3 != nil || accountNumber <= 0 || gen < 0 || !memoryIDPattern.MatchString(person) || len(person) > 64 || expiry < time.Now().Unix() || expiry > time.Now().Unix()+300 {
		return MemoryEntity{}, errors.New("invalid_memory_actor")
	}
	expected := memoryAttestation(secret, p.User.Id, account, person, generation, expires)
	if !hmac.Equal([]byte(expected), []byte(c.GetHeader("X-Memory-Signature"))) {
		return MemoryEntity{}, errors.New("memory_service_attestation_required")
	}
	cloudID := "re_" + hash([]byte(strings.Join([]string{strconv.Itoa(p.User.Id), account, person, generation}, ":")))[:60]
	return MemoryEntity{CloudUserID: cloudID, UserID: p.User.Id, TokenID: p.Token.Id, ProductAccount: account, PersonID: person, Generation: gen, State: "active", CreatedAt: time.Now().Unix()}, nil
}
func memoryPortraitEnabled() bool {
	return os.Getenv("BAILIAN_MEMORY_PORTRAIT_ENABLED") == "1" && os.Getenv("BAILIAN_MEMORY_PORTRAIT_DELETE_VERIFIED") == "1" && os.Getenv("BAILIAN_MEMORY_PORTRAIT_COUNT_VERIFIED") == "1"
}
func (g *Gateway) memoryProductProxy(c *gin.Context, p Principal) {
	actor, e := authorizeMemoryActor(c, p)
	if e != nil {
		failure(c, 403, e.Error())
		return
	}
	if !g.acquire(p.User.Id) {
		failure(c, 429, "gateway_busy")
		return
	}
	defer g.release(p.User.Id)
	id, _ := strconv.Atoi(os.Getenv("BAILIAN_MEMORY_CHANNEL_ID"))
	var channel model.Channel
	if g.DB.First(&channel, id).Error != nil || channel.Type != 17 || channel.Status != model.ChannelStatusEnabled || channel.Key == "" || !listHas(channel.Group, p.User.Group) {
		failure(c, 503, "memory_channel_unavailable")
		return
	}
	if e = g.DB.Clauses(clause.OnConflict{DoNothing: true}).Create(&actor).Error; e != nil {
		failure(c, 503, "memory_entity_store_unavailable")
		return
	}
	var stored MemoryEntity
	if g.DB.First(&stored, "cloud_user_id = ?", actor.CloudUserID).Error != nil || stored.UserID != p.User.Id || stored.ProductAccount != actor.ProductAccount {
		failure(c, 403, "memory_entity_not_owned")
		return
	}
	if stored.TokenID != p.Token.Id {
		if e = g.DB.Model(&stored).Update("token_id", p.Token.Id).Error; e != nil {
			failure(c, 503, "memory_wallet_refresh_pending")
			return
		}
	}
	path := strings.TrimPrefix(c.Request.URL.Path, memoryPrefix+"/")
	method := c.Request.Method
	if path == "entities/retire" {
		if e = g.DB.Model(&stored).Update("state", "retired").Error; e != nil {
			failure(c, 503, "entity_retirement_pending")
			return
		}
		if e = g.DB.Model(&MemoryRequest{}).Where("cloud_user_id = ? AND path = ?", actor.CloudUserID, "memory_nodes/search").Update("response", "").Error; e != nil {
			failure(c, 503, "cache_retirement_pending")
			return
		}
		c.JSON(200, gin.H{"retired": true, "cloud_deleted": false})
		return
	}
	if path == "entities/cleanup-complete" {
		if stored.State != "retired" || stored.PortraitWritten {
			failure(c, 409, "entity_cleanup_not_verified")
			return
		}
		if e = g.DB.Model(&stored).Update("cleanup_confirmed", true).Error; e != nil {
			failure(c, 503, "cleanup_confirmation_pending")
			return
		}
		c.JSON(200, gin.H{"cleanup_confirmed": true, "count_verification_pending": true})
		return
	}
	if strings.HasPrefix(path, "operations/") {
		var request MemoryRequest
		if g.DB.First(&request, "id = ? AND user_id = ? AND cloud_user_id = ?", c.Param("id"), actor.UserID, actor.CloudUserID).Error != nil {
			failure(c, 404, "operation_not_found")
			return
		}
		if request.State == "complete" && request.Status >= 200 && request.Status < 300 && request.Response != "" {
			var result map[string]interface{}
			if json.Unmarshal([]byte(request.Response), &result) == nil {
				if e = g.rememberMemoryResources(actor, result); e != nil {
					failure(c, 503, "resource_index_pending")
					return
				}
			}
			if e = g.recoverMemorySettlement(&request); e != nil {
				failure(c, 503, "memory_settlement_pending")
				return
			}
			c.JSON(200, gin.H{"state": request.State, "status": request.Status, "result": result})
			return
		}
		c.JSON(200, gin.H{"state": request.State, "status": request.Status})
		return
	}
	if stored.State != "active" && (path == "add" || path == "add-async" || path == "memory_nodes/search") {
		failure(c, 409, "memory_entity_retired")
		return
	}
	query, e := url.ParseQuery(c.Request.URL.RawQuery)
	if e != nil {
		failure(c, 400, "invalid_query")
		return
	}
	for key, values := range query {
		if len(values) != 1 || (key != "user_id" && key != "page_num" && key != "page_size" && key != "memory_library_id") {
			failure(c, 400, "query_not_allowed")
			return
		}
	}
	query.Set("user_id", actor.CloudUserID)
	if library := os.Getenv("BAILIAN_MEMORY_LIBRARY_ID"); library != "" {
		query.Set("memory_library_id", library)
	} else {
		query.Del("memory_library_id")
	}
	if objectID := c.Param("id"); objectID != "" {
		if !memoryIDPattern.MatchString(objectID) {
			failure(c, 400, "invalid_resource_id")
			return
		}
		if strings.HasPrefix(path, "memory_nodes/") || strings.HasPrefix(path, "events/") {
			kind := "node"
			if strings.HasPrefix(path, "events/") {
				kind = "event"
			}
			var resource MemoryResource
			if g.DB.First(&resource, "kind = ? AND id = ? AND user_id = ? AND cloud_user_id = ?", kind, objectID, p.User.Id, actor.CloudUserID).Error != nil {
				failure(c, 403, "memory_resource_not_owned")
				return
			}
		} else if strings.HasPrefix(path, "profile_schemas/") {
			schema := os.Getenv("BAILIAN_MEMORY_PROFILE_SCHEMA_ID")
			if !strings.HasSuffix(path, "/user_profile") || !memoryPortraitEnabled() || schema == "" || schema != objectID {
				failure(c, 403, "portrait_operation_not_verified")
				return
			}
		}
	} else if strings.HasPrefix(path, "profile_schemas") {
		failure(c, 403, "schema_maintenance_not_authorized")
		return
	}
	body := map[string]interface{}{}
	raw := []byte("{}")
	if method == http.MethodPost || method == http.MethodPatch {
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 1024*1024)
		raw, e = io.ReadAll(c.Request.Body)
		if e != nil || json.Unmarshal(raw, &body) != nil {
			failure(c, 400, "invalid_memory_body")
			return
		}
		for key := range body {
			switch key {
			case "user_id", "messages", "custom_content", "top_k", "plan_version", "profile_schema", "extract_mode", "memory_library_id", "project_id", "meta_data":
			default:
				failure(c, 400, "body_field_not_allowed")
				return
			}
		}
		body["user_id"] = actor.CloudUserID
		if library := os.Getenv("BAILIAN_MEMORY_LIBRARY_ID"); library != "" {
			body["memory_library_id"] = library
		} else {
			delete(body, "memory_library_id")
		}
	}
	strategy := c.GetHeader("X-Memory-Strategy")
	if strategy == "" {
		strategy = "lite"
	}
	portraitStrategy := c.GetHeader("X-Memory-Portrait-Strategy")
	if portraitStrategy == "" {
		portraitStrategy = "lite"
	}
	operations := []string{}
	if path == "add" || path == "add-async" {
		if _, exists := body["plan_version"]; exists {
			failure(c, 400, "add_version_is_project_setting")
			return
		}
		if _, e = memoryUnitPrice("fact", strategy); e != nil {
			failure(c, 400, e.Error())
			return
		}
		project := os.Getenv("BAILIAN_MEMORY_FACT_" + strings.ToUpper(strategy) + "_PROJECT_ID")
		defaultStrategy := os.Getenv("BAILIAN_MEMORY_DEFAULT_FACT_STRATEGY")
		if (project == "" && defaultStrategy != strategy) || os.Getenv("BAILIAN_MEMORY_RULES_VERIFIED") != "1" {
			failure(c, 503, "memory_fact_rule_not_verified")
			return
		}
		if project != "" {
			body["project_id"] = project
		} else {
			delete(body, "project_id")
		} // verified default-library rule
		mode, _ := body["extract_mode"].(string)
		if mode != "" && mode != "profile_only" {
			failure(c, 400, "invalid_extract_mode")
			return
		}
		if schema, exists := body["profile_schema"]; exists {
			if !memoryPortraitEnabled() || schema != os.Getenv("BAILIAN_MEMORY_PROFILE_SCHEMA_ID") || portraitStrategy != os.Getenv("BAILIAN_MEMORY_PROFILE_STRATEGY") {
				failure(c, 503, "portrait_delete_or_count_not_verified")
				return
			}
			operations = append(operations, "portrait")
		} else if mode == "profile_only" {
			failure(c, 400, "profile_schema_required")
			return
		}
		if mode != "profile_only" {
			operations = append(operations, "fact")
		}
		delete(body, "meta_data") // backend ownership cannot be overwritten with arbitrary metadata
	} else if path == "memory_nodes/search" {
		if _, e = memoryUnitPrice("search", strategy); e != nil {
			failure(c, 400, e.Error())
			return
		}
		body["plan_version"] = strategy
		topK, _ := strconv.Atoi(os.Getenv("BAILIAN_MEMORY_TOP_K"))
		if topK < 1 || topK > 20 {
			topK = 5
		}
		body["top_k"] = topK
		delete(body, "project_id")
		delete(body, "profile_schema")
		delete(body, "extract_mode")
		operations = append(operations, "search")
	} else if method == http.MethodPatch {
		if _, exists := body["custom_content"]; !exists {
			failure(c, 400, "custom_content_required")
			return
		}
	}
	if len(operations) > 0 && !p.Allows("memory", "memory") {
		failure(c, 403, "memory_token_permission_required")
		return
	}
	if len(operations) > 0 {
		if os.Getenv("BAILIAN_MEMORY_STORAGE_COUNT_VERIFIED") != "1" {
			failure(c, 503, "memory_storage_count_not_verified")
			return
		}
		var debt int64
		if e = g.DB.Model(&MemoryStorageHour{}).Where("user_id = ? AND state IN ?", p.User.Id, []string{"pending", "debt"}).Count(&debt).Error; e != nil {
			failure(c, 503, "memory_storage_ledger_unavailable")
			return
		}
		if debt > 0 {
			failure(c, 402, "memory_storage_payment_pending")
			return
		}
	}
	payload, _ := json.Marshal(body)
	idem := c.GetHeader("Idempotency-Key")
	if len(operations) > 0 && (len(idem) < 8 || len(idem) > 128) {
		failure(c, 400, "idempotency_key_required")
		return
	}
	scope := hash([]byte(strings.Join([]string{strconv.Itoa(p.User.Id), actor.CloudUserID, method, path, idem}, ":")))
	payloadHash := hash(append([]byte(method+":"+path+":"+query.Encode()+":"+strategy+":"+portraitStrategy+":"), payload...))
	unlock := g.lockScope(scope)
	defer unlock()
	request := MemoryRequest{ID: scope, UserID: p.User.Id, CloudUserID: actor.CloudUserID, PayloadHash: payloadHash, Path: path, State: "prepared", CreatedAt: time.Now().Unix()}
	persisted := len(operations) > 0
	if persisted {
		if e = g.DB.Clauses(clause.OnConflict{DoNothing: true}).Create(&request).Error; e != nil {
			failure(c, 503, "memory_request_store_unavailable")
			return
		}
		if e = g.DB.First(&request, "id = ?", scope).Error; e != nil || request.PayloadHash != payloadHash {
			failure(c, 409, "idempotency_payload_conflict")
			return
		}
		if request.State != "prepared" {
			if request.State == "complete" && request.Response != "" {
				if request.Status >= 200 && request.Status < 300 {
					var cached map[string]interface{}
					if json.Unmarshal([]byte(request.Response), &cached) != nil || g.rememberMemoryResources(actor, cached) != nil {
						failure(c, 503, "resource_index_pending")
						return
					}
					if e = g.recoverMemorySettlement(&request); e != nil {
						failure(c, 503, "memory_settlement_pending")
						return
					}
				}
				c.Header("X-Memory-Replay", "1")
				c.Data(request.Status, "application/json", []byte(request.Response))
				return
			}
			failure(c, 409, "memory_result_unknown_requires_reconciliation")
			return
		}
	}
	charges := []*MemoryCharge{}
	if !g.memoryRateAllow(path, time.Now()) {
		failure(c, 429, "memory_account_rate_limit")
		return
	}
	for _, operation := range operations {
		plan := strategy
		if operation == "portrait" {
			plan = portraitStrategy
		}
		charge, err := g.reserveMemoryCharge(p, channel, &request, operation, plan, 1)
		if err != nil {
			for _, held := range charges {
				g.releaseMemoryCharge(held, "memory_not_submitted")
			}
			g.DB.Model(&request).Update("state", "rejected")
			if errors.Is(err, model.ErrBLQuota) {
				failure(c, 402, "insufficient_quota")
			} else {
				failure(c, 503, "memory_reservation_failed")
			}
			return
		}
		charges = append(charges, charge)
	}
	if persisted {
		e = g.DB.Transaction(func(tx *gorm.DB) error {
			result := tx.Model(&MemoryRequest{}).Where("id = ? AND state = ?", scope, "prepared").Update("state", "submitted")
			if result.Error != nil {
				return result.Error
			}
			if result.RowsAffected != 1 {
				return model.ErrBLConflict
			}
			for _, charge := range charges {
				claimed, err := claimMemorySubmit(tx, charge)
				if err != nil {
					return err
				}
				if !claimed {
					return model.ErrBLConflict
				}
			}
			if schema, exists := body["profile_schema"]; exists && schema != "" {
				return tx.Model(&stored).Update("portrait_written", true).Error
			}
			return nil
		})
		if e != nil {
			failure(c, 409, "memory_submission_already_claimed")
			return
		}
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 85*time.Second)
	defer cancel()
	target := memoryUpstream + path
	if method == http.MethodGet || method == http.MethodDelete {
		target += "?" + query.Encode()
	}
	httpReq, _ := http.NewRequestWithContext(ctx, method, target, bytes.NewReader(payload))
	httpReq.Header.Set("Authorization", "Bearer "+strings.TrimSpace(channel.Key))
	httpReq.Header.Set("Content-Type", "application/json")
	response, e := memoryClient.Do(httpReq)
	if e != nil {
		g.memoryUnknown(&request, charges)
		failure(c, 502, "memory_upstream_result_unknown")
		return
	}
	defer response.Body.Close()
	responseBody, e := io.ReadAll(io.LimitReader(response.Body, 4*1024*1024+1))
	if e != nil || len(responseBody) > 4*1024*1024 || response.StatusCode >= 300 && response.StatusCode < 400 {
		g.memoryUnknown(&request, charges)
		failure(c, 502, "memory_upstream_response_unknown")
		return
	}
	var result map[string]interface{}
	if json.Unmarshal(responseBody, &result) != nil {
		g.memoryUnknown(&request, charges)
		failure(c, 502, "memory_upstream_invalid_json")
		return
	}
	requestID, _ := result["request_id"].(string)
	if persisted {
		// Persist accepted response before settlement, so restart can finish without another call.
		if e = g.DB.Model(&request).Updates(map[string]interface{}{"state": "complete", "status": response.StatusCode, "response": string(responseBody), "request_id": requestID}).Error; e != nil {
			g.memoryUnknown(&request, charges)
			failure(c, 503, "memory_response_persist_failed")
			return
		}
	}
	if response.StatusCode >= 200 && response.StatusCode < 300 {
		if e = g.rememberMemoryResources(actor, result); e != nil {
			failure(c, 503, "memory_resource_index_failed")
			return
		}
		for _, charge := range charges {
			if e = g.settleMemoryCharge(charge); e != nil {
				failure(c, 503, "memory_settlement_pending")
				return
			}
		}
		if schema, exists := body["profile_schema"]; exists && schema != "" {
			g.DB.Model(&stored).Update("portrait_written", true)
		}
		if method == http.MethodDelete || method == http.MethodPatch {
			g.DB.Model(&MemoryRequest{}).Where("cloud_user_id = ?", actor.CloudUserID).Update("response", "")
		}
	} else if response.StatusCode >= 400 && response.StatusCode < 500 && response.StatusCode != 408 && response.StatusCode != 429 {
		for _, charge := range charges {
			g.releaseMemoryCharge(charge, "memory_upstream_rejected")
		}
	} else {
		g.memoryUnknown(&request, charges)
	}
	c.Header("Cache-Control", "no-store")
	c.Header("X-Memory-Cloud-User", actor.CloudUserID)
	c.Header("X-Memory-Price-Version", memoryResponsePrice(charges))
	c.Data(response.StatusCode, "application/json", responseBody)
}

func (g *Gateway) memoryUnknown(request *MemoryRequest, charges []*MemoryCharge) {
	if len(charges) == 0 {
		return
	}
	g.DB.Model(request).Update("state", "review")
	for _, charge := range charges {
		g.markMemoryUnknown(charge)
		g.DB.Model(charge).Update("state", "review")
	}
}
func (g *Gateway) recoverMemorySettlement(request *MemoryRequest) error {
	if request.Status < 200 || request.Status >= 300 {
		return nil
	}
	var charges []MemoryCharge
	if e := g.DB.Where("request_id = ? AND state <> ?", request.ID, "settled").Find(&charges).Error; e != nil {
		return e
	}
	for i := range charges {
		if e := g.settleMemoryCharge(&charges[i]); e != nil {
			return e
		}
	}
	return nil
}
func (g *Gateway) rememberMemoryResources(actor MemoryEntity, result map[string]interface{}) error {
	// Only traverse documented result containers; resource_id on events is a project/schema ID.
	var visit func(interface{}, string) error
	visit = func(value interface{}, kind string) error {
		switch v := value.(type) {
		case []interface{}:
			for _, item := range v {
				if e := visit(item, kind); e != nil {
					return e
				}
			}
		case map[string]interface{}:
			if user, ok := v["user_id"].(string); ok && user != "" && user != actor.CloudUserID {
				return errors.New("upstream_entity_mismatch")
			}
			id, _ := v["memory_node_id"].(string)
			if id == "" && kind == "node" {
				id, _ = v["id"].(string)
			}
			actualKind := "node"
			if eventID, ok := v["event_id"].(string); ok && eventID != "" {
				id = eventID
				actualKind = "event"
			}
			if id != "" && memoryIDPattern.MatchString(id) {
				resource := MemoryResource{Kind: actualKind, ID: id, CloudUserID: actor.CloudUserID, UserID: actor.UserID}
				if e := g.DB.Clauses(clause.OnConflict{DoNothing: true}).Create(&resource).Error; e != nil {
					return e
				}
				var existing MemoryResource
				if g.DB.First(&existing, "kind = ? AND id = ?", actualKind, id).Error != nil || existing.CloudUserID != actor.CloudUserID {
					return errors.New("resource_owner_conflict")
				}
			}
			for _, key := range []string{"memory_nodes", "result", "results", "events", "event"} {
				if child, ok := v[key]; ok {
					next := "node"
					if key == "events" || key == "event" {
						next = "event"
					}
					if e := visit(child, next); e != nil {
						return e
					}
				}
			}
		}
		return nil
	}
	return visit(result, "")
}
