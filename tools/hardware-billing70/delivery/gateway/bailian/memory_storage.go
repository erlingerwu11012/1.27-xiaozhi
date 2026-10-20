package bailian

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm/clause"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"time"
)

// Samples are immutable. Missing historical samples are never fabricated from
// today's count. The evidence request and sample time remain available to audit.
func (g *Gateway) collectMemoryStorage(ctx context.Context, now time.Time) error {
	if os.Getenv("BAILIAN_MEMORY_STORAGE_COUNT_VERIFIED") != "1" {
		return errors.New("storage_count_not_verified")
	}
	var channel model.Channel
	id, _ := strconv.Atoi(os.Getenv("BAILIAN_MEMORY_CHANNEL_ID"))
	if e := g.DB.First(&channel, id).Error; e != nil {
		return e
	}
	if channel.Type != 17 || channel.Status != model.ChannelStatusEnabled || channel.Key == "" {
		return errors.New("memory_channel_unavailable")
	}
	var entities []MemoryEntity
	if e := g.DB.Where("state <> ?", "deleted").Order("created_at, cloud_user_id").Find(&entities).Error; e != nil {
		return e
	}
	failures := 0
	for _, entity := range entities {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if entity.PortraitWritten {
			return errors.New("portrait_storage_count_not_verified")
		}
		hour := now.UTC().Unix() / 3600
		sampleID := hash([]byte(entity.CloudUserID + ":" + strconv.FormatInt(hour, 10)))
		var prior MemoryStorageHour
		if g.DB.First(&prior, "id = ?", sampleID).Error == nil {
			continue
		}
		if !g.memoryRateAllow("memory_nodes", time.Now()) {
			return errors.New("storage_account_rate_limit")
		}
		query := url.Values{"user_id": {entity.CloudUserID}, "page_num": {"1"}, "page_size": {"1"}}
		if library := os.Getenv("BAILIAN_MEMORY_LIBRARY_ID"); library != "" {
			query.Set("memory_library_id", library)
		}
		check, cancel := context.WithTimeout(ctx, 3*time.Second)
		request, e := http.NewRequestWithContext(check, http.MethodGet, memoryUpstream+"memory_nodes?"+query.Encode(), nil)
		if e != nil {
			cancel()
			return e
		}
		request.Header.Set("Authorization", "Bearer "+channel.Key)
		response, e := memoryClient.Do(request)
		if e != nil {
			cancel()
			failures++
			continue
		}
		raw, e := io.ReadAll(io.LimitReader(response.Body, 1024*1024+1))
		response.Body.Close()
		cancel()
		if e != nil || len(raw) > 1024*1024 || response.StatusCode != 200 {
			failures++
			continue
		}
		var result struct {
			Total     *int64 `json:"total"`
			RequestID string `json:"request_id"`
			Nodes     []struct {
				UserID string `json:"user_id"`
			} `json:"memory_nodes"`
		}
		if json.Unmarshal(raw, &result) != nil || result.Total == nil || *result.Total < 0 || result.RequestID == "" {
			failures++
			continue
		}
		valid := true
		for _, node := range result.Nodes {
			if node.UserID != "" && node.UserID != entity.CloudUserID {
				valid = false
			}
		}
		if !valid {
			failures++
			continue
		}
		exact, e := memoryExactQuota("storage", "lite", *result.Total)
		if e != nil {
			return e
		}
		sample := MemoryStorageHour{ID: sampleID, CloudUserID: entity.CloudUserID, UserID: entity.UserID, TokenID: entity.TokenID, ChannelID: channel.Id, Hour: hour, FactCount: *result.Total, State: "pending", ExactQuota: exact.RatString(), EvidenceRequestID: result.RequestID, SampledAt: now.Unix()}
		if *result.Total == 0 {
			sample.State = "settled"
		}
		if e = g.DB.Clauses(clause.OnConflict{DoNothing: true}).Create(&sample).Error; e != nil {
			return e
		}
		// Retired entities are only finished after confirmed deletion and after
		// every possibly late Add has a definitive outcome.
		if entity.State == "retired" && *result.Total == 0 {
			var unresolved int64
			g.DB.Model(&MemoryRequest{}).Where("cloud_user_id = ? AND path IN ? AND state IN ?", entity.CloudUserID, []string{"add", "add-async"}, []string{"prepared", "submitted", "review"}).Count(&unresolved)
			if unresolved == 0 && entity.CleanupConfirmed {
				g.DB.Model(&entity).Update("state", "deleted")
			}
		}
	}
	if err := g.settleMemoryStorageDebt(); err != nil {
		return err
	}
	if failures > 0 {
		return fmt.Errorf("storage_sampling_failed_entities=%d", failures)
	}
	return nil
}

func (g *Gateway) settleMemoryStorageDebt() error {
	var samples []MemoryStorageHour
	if e := g.DB.Where("state IN ?", []string{"pending", "debt"}).Order("hour, id").Limit(1000).Find(&samples).Error; e != nil {
		return e
	}
	for i := range samples {
		sample := &samples[i]
		var p Principal
		if g.DB.First(&p.User, sample.UserID).Error != nil || g.DB.First(&p.Token, sample.TokenID).Error != nil {
			continue
		}
		// A rotated product token can settle the same account's storage debt.
		var entity MemoryEntity
		if g.DB.First(&entity, "cloud_user_id = ?", sample.CloudUserID).Error == nil && entity.TokenID != sample.TokenID {
			if g.DB.First(&p.Token, entity.TokenID).Error != nil {
				continue
			}
		}
		request := MemoryRequest{ID: sample.ID, CloudUserID: sample.CloudUserID, PayloadHash: hash([]byte(sample.ExactQuota + ":" + sample.EvidenceRequestID))}
		charge, e := g.reserveMemoryCharge(p, model.Channel{Id: sample.ChannelID}, &request, "storage", "lite", sample.FactCount)
		if e != nil {
			g.DB.Model(sample).Update("state", "debt")
			continue
		}
		if !isHardwareMemory(charge) {
			var bill model.BailianBill
			if e = g.DB.First(&bill, "id = ?", charge.BillID).Error; e != nil {
				return e
			}
			if bill.State != model.BLSettled {
				if e = model.SubmitBailian(g.DB, charge.BillID); e != nil {
					return e
				}
			}
		}
		if e = g.settleMemoryCharge(charge); e != nil {
			return e
		}
		if isHardwareMemory(charge) {
			var refreshed MemoryCharge
			if e = g.DB.First(&refreshed, "id = ?", charge.ID).Error; e != nil {
				return e
			}
			if refreshed.State != "settled" {
				g.DB.Model(sample).Update("state", "debt")
				continue
			}
		}
		if e = g.DB.Model(sample).Updates(map[string]interface{}{"state": "settled", "bill_id": charge.BillID}).Error; e != nil {
			return e
		}
	}
	return nil
}

// The collector is deliberately independent of request authentication and wallet
// balance: retained data continues accruing storage, while deletion stays usable.
func (g *Gateway) StartMemoryAccounting(ctx context.Context) {
	if os.Getenv("BAILIAN_MEMORY_BILLING") != "1" {
		return
	}
	go func() {
		tick := time.NewTicker(time.Minute)
		defer tick.Stop()
		for {
			if err := g.collectMemoryStorage(ctx, time.Now()); err != nil {
				log.Printf("memory storage sampling deferred: %v", err)
			}
			select {
			case <-ctx.Done():
				return
			case <-tick.C:
			}
		}
	}()
}
