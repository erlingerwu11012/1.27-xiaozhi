package bailian

import (
	"encoding/json"
	"errors"
	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"io"
	"strings"
	"time"
)

type MemoryResolution struct {
	OperationID string `gorm:"type:varchar(80);primaryKey"`
	RequestID   string `gorm:"type:char(64);uniqueIndex"`
	PayloadHash string `gorm:"type:char(64)"`
	ActorID     int
	Outcome     string `gorm:"type:varchar(16)"`
	Reason      string `gorm:"type:text"`
	Evidence    string `gorm:"type:text"`
	CreatedAt   int64
}

// This is an audited human reconciliation, not an automated deletion or receipt
// verification. Operators must obtain the upstream outcome before using it.
func (g *Gateway) AdminMemoryResolve(c *gin.Context) {
	p, ok := g.adminPrincipal(c)
	if !ok {
		return
	}
	raw, e := io.ReadAll(io.LimitReader(c.Request.Body, 16385))
	var input struct {
		OperationID string                 `json:"operation_id"`
		Outcome     string                 `json:"outcome"`
		Reason      string                 `json:"reason"`
		Evidence    string                 `json:"evidence"`
		Result      map[string]interface{} `json:"result"`
	}
	if e != nil || len(raw) > 16384 || strictJSON(raw, &input) != nil || len(input.OperationID) < 8 || len(input.OperationID) > 80 || len(strings.TrimSpace(input.Reason)) < 3 || len(strings.TrimSpace(input.Evidence)) < 8 || (input.Outcome != "accepted" && input.Outcome != "rejected") {
		failure(c, 400, "confirmed_outcome_reason_evidence_required")
		return
	}
	id := c.Param("id")
	canonical, _ := json.Marshal(input)
	digest := hash(canonical)
	unlock := g.lockScope(id)
	defer unlock()
	e = g.DB.Transaction(func(tx *gorm.DB) error {
		var prior MemoryResolution
		if tx.First(&prior, "operation_id = ?", input.OperationID).Error == nil {
			if prior.RequestID != id || prior.PayloadHash != digest {
				return model.ErrBLConflict
			}
			return nil
		}
		var request MemoryRequest
		if err := tx.First(&request, "id = ?", id).Error; err != nil {
			return err
		}
		// Use the same wallet lock order as automatic settlement.
		var wallet model.User
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&wallet, request.UserID).Error; err != nil {
			return err
		}
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&request, "id = ?", id).Error; err != nil {
			return err
		}
		if request.State != "review" && request.State != "submitted" {
			return model.ErrBLConflict
		}
		var charges []MemoryCharge
		if err := tx.Where("request_id = ?", id).Find(&charges).Error; err != nil {
			return err
		}
		if len(charges) == 0 {
			return model.ErrBLConflict
		}
		if input.Outcome == "accepted" {
			requestID, _ := input.Result["request_id"].(string)
			if !memoryIDPattern.MatchString(requestID) {
				return errors.New("upstream_request_evidence_required")
			}
			if request.Path == "add-async" {
				eventID, _ := input.Result["event_id"].(string)
				if !memoryIDPattern.MatchString(eventID) {
					return errors.New("confirmed_event_required")
				}
			} else if request.Path == "memory_nodes/search" {
				if _, ok := input.Result["memory_nodes"].([]interface{}); !ok {
					return errors.New("confirmed_search_result_required")
				}
			} else {
				return errors.New("unsupported_manual_outcome")
			}
			scoped := NewGateway(g.Context, tx)
			actor := MemoryEntity{CloudUserID: request.CloudUserID, UserID: request.UserID}
			if err := scoped.rememberMemoryResources(actor, input.Result); err != nil {
				return err
			}
			response, _ := json.Marshal(input.Result)
			if err := tx.Model(&request).Updates(map[string]interface{}{"state": "complete", "status": 200, "response": string(response), "request_id": requestID}).Error; err != nil {
				return err
			}
			for i := range charges {
				if err := tx.Model(&model.BailianBill{}).Where("id = ? AND state IN ?", charges[i].BillID, []string{model.BLReview, model.BLSubmitted}).Update("state", model.BLSubmitted).Error; err != nil {
					return err
				}
				if err := scoped.settleMemoryCharge(&charges[i]); err != nil {
					return err
				}
			}
		} else {
			for _, charge := range charges {
				scoped := NewGateway(g.Context, tx)
				if isHardwareMemory(&charge) {
					if err := scoped.releaseMemoryCharge(&charge, "memory_confirmed_not_accepted"); err != nil {
						return err
					}
				} else {
					if err := model.FinishBailian(tx, charge.BillID, 0, false, p.User.Id, "memory_confirmed_not_accepted"); err != nil {
						return err
					}
				}
				if err := tx.Model(&charge).Update("state", "refunded").Error; err != nil {
					return err
				}
			}
			if err := tx.Model(&request).Updates(map[string]interface{}{"state": "rejected", "status": 400, "response": ""}).Error; err != nil {
				return err
			}
		}
		return tx.Create(&MemoryResolution{OperationID: input.OperationID, RequestID: id, PayloadHash: digest, ActorID: p.User.Id, Outcome: input.Outcome, Reason: input.Reason, Evidence: input.Evidence, CreatedAt: time.Now().Unix()}).Error
	})
	if e != nil {
		failure(c, 409, "memory_resolution_conflict_or_invalid_evidence")
		return
	}
	c.JSON(200, gin.H{"reconciled": true, "outcome": input.Outcome, "operation_id": input.OperationID})
}
