package bailian

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm"
)

type PrivateVoice struct {
	ID                uint64 `json:"id" gorm:"primaryKey"`
	UserID            int    `json:"user_id" gorm:"index"`
	VoiceID           string `json:"voice_id" gorm:"type:varchar(128);index"`
	Model             string `json:"model" gorm:"type:varchar(160)"`
	Region            string `json:"region" gorm:"type:varchar(32)"`
	ChannelID         int    `json:"channel_id"`
	Status            string `json:"status" gorm:"type:varchar(32);index"`
	Kind              string `json:"kind" gorm:"type:varchar(16)"`
	TaskID            string `json:"task_id" gorm:"type:varchar(64);index"`
	PayloadHash       string `json:"payload_hash" gorm:"type:char(64)"`
	BillID            string `json:"bill_id" gorm:"type:varchar(64);index"`
	Error             string `json:"error" gorm:"type:varchar(256)"`
	GrantSource       string `json:"grant_source" gorm:"type:varchar(32)"`
	AllowUse          bool   `json:"allow_use"`
	AllowDelete       bool   `json:"allow_delete"`
	GrantedBy         int    `json:"granted_by"`
	GrantReason       string `json:"grant_reason" gorm:"type:varchar(256)"`
	UpstreamRequestID string `json:"upstream_request_id" gorm:"type:varchar(80)"`
	UpstreamStatus    string `json:"upstream_status" gorm:"type:varchar(32)"`
	AudioSHA256       string `json:"audio_sha256" gorm:"type:char(64)"`
	CreatedAt         int64  `json:"created_at"`
	UpdatedAt         int64  `json:"updated_at"`
}

func (PrivateVoice) TableName() string { return "bailian_private_voices" }

type SynthArtifact struct {
	BillID      string `json:"bill_id" gorm:"type:varchar(64);primaryKey"`
	UserID      int    `json:"user_id" gorm:"index"`
	PayloadHash string `json:"payload_hash" gorm:"type:char(64)"`
	Status      string `json:"status" gorm:"type:varchar(24)"`
	Format      string `json:"format" gorm:"type:varchar(16)"`
	ContentType string `json:"content_type" gorm:"type:varchar(64)"`
	RelPath     string `json:"rel_path" gorm:"type:varchar(256)"`
	Characters  int64  `json:"characters"`
	Error       string `json:"error" gorm:"type:varchar(256)"`
	CreatedAt   int64  `json:"created_at"`
}

func (SynthArtifact) TableName() string { return "bailian_synth_artifacts" }

func MigratePrivateVoices(db *gorm.DB) error {
	if e := db.AutoMigrate(&PrivateVoice{}, &SynthArtifact{}); e != nil {
		return e
	}
	return MigrateOperationPrices(db)
}

func ListPrivateVoiceIDs(db *gorm.DB, userID int, modelName string) []string {
	var rows []PrivateVoice
	if e := db.Where("user_id = ? AND model = ? AND status = ? AND allow_use = ?", userID, modelName, "available", true).Find(&rows).Error; e != nil {
		return nil
	}
	out := make([]string, 0, len(rows))
	for _, row := range rows {
		if row.VoiceID != "" {
			out = append(out, row.VoiceID)
		}
	}
	return out
}

func (g *Gateway) httpAuth(c *gin.Context) (Principal, bool) {
	if c.GetHeader("Origin") != "" {
		failure(c, 403, "server_to_server_only")
		return Principal{}, false
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
	defer cancel()
	p, e := Authenticate(g.DB.WithContext(ctx), c.Request, c.ClientIP())
	if e != nil {
		failure(c, 401, "authentication_failed")
		return p, false
	}
	return p, true
}

func (g *Gateway) VoiceList(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	cap, e := loadCapability(g.DB, TargetTTSPlus, "cn-beijing", "/api-ws/v1/inference")
	if e != nil {
		failure(c, 403, "model_not_allowed_or_not_verified")
		return
	}
	var private []PrivateVoice
	_ = g.DB.Where("user_id = ?", p.User.Id).Order("id DESC").Limit(200).Find(&private).Error
	c.JSON(200, gin.H{"catalog": strings.Split(cap.Voices, ","), "private": private})
}

func (g *Gateway) VoiceClone(c *gin.Context)  { g.submitVoice(c, "clone") }
func (g *Gateway) VoiceDesign(c *gin.Context) { g.submitVoice(c, "design") }

type voiceCanon struct {
	Kind          string   `json:"kind"`
	Model         string   `json:"model"`
	Prefix        string   `json:"prefix"`
	AudioURL      string   `json:"audio_url"`
	AudioSHA256   string   `json:"audio_sha256"`
	Prompt        string   `json:"prompt"`
	PreviewText   string   `json:"preview_text"`
	LanguageHints []string `json:"language_hints"`
}

func (g *Gateway) submitVoice(c *gin.Context, kind string) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	raw, e := io.ReadAll(io.LimitReader(c.Request.Body, 64*1024))
	if e != nil {
		failure(c, 400, "invalid_json")
		return
	}
	var req struct {
		Model         string   `json:"model"`
		Prefix        string   `json:"prefix"`
		AudioURL      string   `json:"audio_url"`
		AudioSHA256   string   `json:"audio_sha256"`
		Prompt        string   `json:"prompt"`
		PreviewText   string   `json:"preview_text"`
		LanguageHints []string `json:"language_hints"`
		Idempotency   string   `json:"idempotency_key"`
		Region        string   `json:"region"`
	}
	if strictJSON(raw, &req) != nil || req.Model == "" {
		failure(c, 400, "invalid_voice_request")
		return
	}
	if kind == "clone" {
		if req.AudioURL == "" || !allowedMediaURL(req.AudioURL) {
			failure(c, 400, "audio_url_not_allowed")
			return
		}
		if !validSHA256Hex(req.AudioSHA256) {
			failure(c, 400, "audio_sha256_required")
			return
		}
	}
	if kind == "design" {
		if strings.TrimSpace(req.Prompt) == "" || strings.TrimSpace(req.PreviewText) == "" {
			failure(c, 400, "design_prompt_and_preview_required")
			return
		}
	}
	region := req.Region
	if region == "" {
		region = "cn-beijing"
	}
	cap, e := loadCapability(g.DB, req.Model, region, "/api-ws/v1/inference")
	if e != nil || cap.Protocol != "tts_inference" || !p.Allows(req.Model, cap.Model) {
		failure(c, 403, "model_not_allowed_or_not_verified")
		return
	}
	idem := strings.TrimSpace(c.GetHeader("Idempotency-Key"))
	if idem == "" {
		idem = strings.TrimSpace(req.Idempotency)
	}
	if idem == "" {
		failure(c, 400, "idempotency_key_required")
		return
	}
	canon, _ := json.Marshal(voiceCanon{
		Kind: kind, Model: cap.Model, Prefix: req.Prefix, AudioURL: req.AudioURL,
		AudioSHA256: req.AudioSHA256, Prompt: req.Prompt, PreviewText: req.PreviewText,
		LanguageHints: req.LanguageHints,
	})
	payloadHash := hash(canon)
	scope := userScope("voice", kind, p.User.Id, idem)
	unlock := g.lockScope(scope)
	defer unlock()
	if existing, reused, err := g.reuseVoice(p.User.Id, payloadHash, scope); err != nil {
		failure(c, 409, "idempotency_payload_conflict")
		return
	} else if reused {
		c.JSON(200, voiceView(g.DB, existing, true))
		return
	}
	var priorBill model.BailianBill
	if g.DB.Where("scope = ?", scope).Take(&priorBill).Error == nil {
		if priorBill.UserID != p.User.Id || priorBill.PayloadHash != payloadHash {
			failure(c, 409, "idempotency_payload_conflict")
			return
		}
		if priorBill.State != model.BLReserved {
			c.JSON(200, gin.H{
				"task_id": "", "status": "uncertain", "bill_id": priorBill.ID, "reused": true,
				"review": true, "error": "submitted_without_task_row",
				"reserved": priorBill.Held, "settled": priorBill.Charged, "quota": priorBill.Held,
			})
			return
		}
	}
	channel, price, bill, amount, errCode := g.reserveHTTP(p, cap, model.Channel{}, scope, payloadHash, kind, 1)
	if errCode != "" {
		code := 402
		if errCode == "idempotency_payload_conflict" {
			code = 409
		}
		failure(c, code, errCode)
		return
	}
	if existing, reused, err := g.reuseVoice(p.User.Id, payloadHash, scope); err != nil {
		failure(c, 409, "idempotency_payload_conflict")
		return
	} else if reused {
		c.JSON(200, voiceView(g.DB, existing, true))
		return
	}
	taskID := uuid.NewString()
	now := time.Now().Unix()
	row := PrivateVoice{
		UserID: p.User.Id, Model: cap.Model, Region: cap.Region, ChannelID: channel.Id,
		Status: "processing", Kind: kind, TaskID: taskID, PayloadHash: payloadHash,
		BillID: bill.ID, GrantSource: kind, AllowUse: false, AllowDelete: true,
		AudioSHA256: req.AudioSHA256, CreatedAt: now, UpdatedAt: now,
	}
	if e = g.DB.Create(&row).Error; e != nil {
		_ = model.FinishBailian(g.DB, bill.ID, 0, true, 0, "voice_persist_uncertain")
		failure(c, 503, "voice_persist_uncertain")
		return
	}
	claimed, e := model.ClaimSubmitBailian(g.DB, bill.ID)
	if e != nil {
		row.Status, row.Error = "uncertain", "ledger_unavailable"
		row.UpdatedAt = time.Now().Unix()
		_ = g.DB.Save(&row).Error
		failure(c, 503, "ledger_unavailable")
		return
	}
	if !claimed {
		c.JSON(200, voiceView(g.DB, &row, true))
		return
	}
	var upBody []byte
	if kind == "clone" {
		upBody, e = BuildCloneEnrollment(cap.Model, req.Prefix, req.AudioURL, req.LanguageHints)
	} else {
		upBody, e = BuildDesignEnrollment(cap.Model, req.Prefix, req.Prompt, req.PreviewText)
	}
	if e != nil {
		row.Status, row.Error = "failed", e.Error()
		row.UpdatedAt = time.Now().Unix()
		_ = g.DB.Save(&row).Error
		_ = model.FinishBailian(g.DB, bill.ID, 0, false, 0, "invalid_enrollment")
		failure(c, 400, e.Error())
		return
	}
	upURL, e := UpstreamHTTP(*channel.BaseURL, "POST", HTTPPathCustomization)
	if e != nil {
		row.Status, row.Error = "uncertain", "upstream_configuration_error"
		_ = g.DB.Save(&row).Error
		_ = model.FinishBailian(g.DB, bill.ID, 0, true, 0, "upstream_configuration_error")
		failure(c, 500, "upstream_configuration_error")
		return
	}
	status, body, err := g.proxyUpstream(c.Request.Context(), "POST", upURL, channel.Key, upBody)
	review := false
	reason := "completed"
	charged := amount
	previewAudio := ""
	if err != nil {
		review, reason, charged = true, "upstream_uncertain", 0
		row.Status, row.Error = "uncertain", reason
	} else if status == 429 || status >= 500 {
		review, reason, charged = true, "upstream_unavailable", 0
		row.Status, row.Error = "uncertain", reason
	} else if status < 200 || status >= 300 {
		reason, charged = "upstream_rejected", 0
		row.Status = "failed"
		if msg := upstreamRejectReason(body); msg != "" {
			row.Error = msg
		} else {
			row.Error = reason
		}
	} else {
		parsed, pe := ParseCreateVoiceResponse(body)
		if pe != nil {
			review, reason, charged = true, pe.Error(), 0
			row.Status, row.Error = "uncertain", reason
		} else {
			row.VoiceID = parsed.VoiceID
			row.UpstreamRequestID = parsed.RequestID
			previewAudio = parsed.PreviewAudio
			mapped, qerr := g.refreshOfficialVoice(&row, channel)
			if qerr != nil {
				row.Status, row.Error = "processing", "query_after_create_deferred"
			} else {
				row.Status = mapped
			}
		}
	}
	row.UpdatedAt = time.Now().Unix()
	if e = g.DB.Save(&row).Error; e != nil {
		review, reason = true, "voice_persist_uncertain"
	}
	if e = model.FinishBailian(g.DB, bill.ID, charged, review, 0, reason); e != nil {
		review = true
	}
	_ = price
	view := voiceView(g.DB, &row, false)
	if previewAudio != "" {
		view["preview_audio"] = previewAudio
	}
	c.JSON(200, view)
}

func (g *Gateway) refreshOfficialVoice(row *PrivateVoice, channel model.Channel) (string, error) {
	if row.VoiceID == "" {
		return "", errors.New("missing_voice_id")
	}
	upBody, e := BuildQueryVoice(row.VoiceID)
	if e != nil {
		return "", e
	}
	upURL, e := UpstreamHTTP(*channel.BaseURL, "POST", HTTPPathCustomization)
	if e != nil {
		return "", e
	}
	status, body, err := g.proxyUpstream(context.Background(), "POST", upURL, channel.Key, upBody)
	if err != nil || status == 429 || status >= 500 {
		return "", errors.New("query_uncertain")
	}
	if status < 200 || status >= 300 {
		return "", errors.New("query_rejected")
	}
	parsed, e := ParseQueryVoiceResponse(body)
	if e != nil {
		return "", e
	}
	row.UpstreamStatus = parsed.Status
	row.UpstreamRequestID = parsed.RequestID
	if parsed.TargetModel != "" && parsed.TargetModel != row.Model {
		return "", errors.New("query_model_mismatch")
	}
	mapped, e := MapOfficialVoiceStatus(parsed.Status)
	if e != nil {
		return "", e
	}
	if mapped == "available" {
		row.AllowUse = true
	}
	return mapped, nil
}

func voiceView(db *gorm.DB, row *PrivateVoice, reused bool) gin.H {
	held, charged := int64(0), int64(0)
	state := ""
	review := false
	if row.BillID != "" {
		var bill model.BailianBill
		if db.Where("id = ?", row.BillID).Take(&bill).Error == nil {
			held, charged, state = bill.Held, bill.Charged, bill.State
			review = bill.State == model.BLReview
		}
	}
	quota := charged
	if quota == 0 && held > 0 {
		quota = held
	}
	return gin.H{
		"task_id": row.TaskID, "voice_id": row.VoiceID, "status": row.Status,
		"bill_id": row.BillID, "reused": reused, "grant_source": row.GrantSource,
		"allow_use": row.AllowUse, "allow_delete": row.AllowDelete,
		"upstream_request_id": row.UpstreamRequestID, "upstream_status": row.UpstreamStatus,
		"quota": quota, "reserved": held, "settled": charged, "bill_state": state, "review": review,
		"error": row.Error,
	}
}

func (g *Gateway) reuseVoice(userID int, payloadHash, scope string) (*PrivateVoice, bool, error) {
	var row PrivateVoice
	e := g.DB.Where("user_id = ? AND bill_id IN (SELECT id FROM bailian_bills WHERE scope = ?)", userID, scope).Take(&row).Error
	if errors.Is(e, gorm.ErrRecordNotFound) {
		var bill model.BailianBill
		if g.DB.Where("scope = ?", scope).Take(&bill).Error == nil {
			if bill.PayloadHash != payloadHash || bill.UserID != userID {
				return nil, false, ErrConflictPayload
			}
		}
		return nil, false, nil
	}
	if e != nil {
		return nil, false, e
	}
	if row.PayloadHash != payloadHash {
		return nil, false, ErrConflictPayload
	}
	return &row, true, nil
}

var ErrConflictPayload = errors.New("idempotency_payload_conflict")

func (g *Gateway) VoiceTask(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	id := c.Param("id")
	if _, e := uuidParse(id); e != nil {
		failure(c, 400, "invalid_task_id")
		return
	}
	var row PrivateVoice
	if e := g.DB.Where("task_id = ? AND user_id = ?", id, p.User.Id).Take(&row).Error; e != nil {
		failure(c, 404, "task_not_found")
		return
	}
	if row.Status == "available" || row.Status == "failed" || row.Status == "pending_authorization" {
		c.JSON(200, voiceView(g.DB, &row, false))
		return
	}
	if row.VoiceID == "" {
		if row.Status != "uncertain" {
			row.Status = "uncertain"
			row.Error = "submitted_without_upstream_voice_id"
			row.UpdatedAt = time.Now().Unix()
			_ = g.DB.Save(&row).Error
		}
		c.JSON(200, voiceView(g.DB, &row, false))
		return
	}
	cap, e := loadCapability(g.DB, row.Model, row.regionOrDefault(), "/api-ws/v1/inference")
	if e != nil {
		failure(c, 403, "model_not_allowed_or_not_verified")
		return
	}
	channel, e := SelectChannelByID(g.DB, p, cap, row.ChannelID)
	if e != nil {
		failure(c, 403, "channel_mismatch")
		return
	}
	mapped, qerr := g.refreshOfficialVoice(&row, channel)
	if qerr != nil {
		row.Status, row.Error = "uncertain", qerr.Error()
	} else {
		row.Status = mapped
		row.Error = ""
	}
	row.UpdatedAt = time.Now().Unix()
	_ = g.DB.Save(&row).Error
	c.JSON(200, voiceView(g.DB, &row, false))
}

func (row PrivateVoice) regionOrDefault() string {
	if row.Region != "" {
		return row.Region
	}
	return "cn-beijing"
}

func (g *Gateway) VoiceImport(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	raw, e := io.ReadAll(io.LimitReader(c.Request.Body, 16*1024))
	if e != nil {
		failure(c, 400, "invalid_json")
		return
	}
	var req struct {
		Model  string `json:"model"`
		Voice  string `json:"voice"`
		Region string `json:"region"`
	}
	if strictJSON(raw, &req) != nil || !validVoiceID(req.Voice) || req.Model == "" {
		failure(c, 400, "invalid_import")
		return
	}
	region := req.Region
	if region == "" {
		region = "cn-beijing"
	}
	cap, e := loadCapability(g.DB, req.Model, region, "/api-ws/v1/inference")
	if e != nil || !p.Allows(req.Model, cap.Model) {
		failure(c, 403, "model_not_allowed_or_not_verified")
		return
	}
	if _, _, e := SnapshotOpPrice(g.DB, p, cap, "import", "count"); e != nil {
		failure(c, 403, "operation_price_unconfigured")
		return
	}
	channel, e := SelectChannel(g.DB, p, cap)
	if e != nil {
		failure(c, 403, "no_authorized_channel")
		return
	}
	var owned PrivateVoice
	if g.DB.Where("voice_id = ? AND user_id = ?", req.Voice, p.User.Id).Take(&owned).Error == nil {
		c.JSON(200, voiceView(g.DB, &owned, true))
		return
	}
	upBody, e := BuildQueryVoice(req.Voice)
	if e != nil {
		failure(c, 400, "invalid_voice")
		return
	}
	upURL, e := UpstreamHTTP(*channel.BaseURL, "POST", HTTPPathCustomization)
	if e != nil {
		failure(c, 500, "upstream_configuration_error")
		return
	}
	status, body, err := g.proxyUpstream(c.Request.Context(), "POST", upURL, channel.Key, upBody)
	if err != nil || status == 429 || status >= 500 {
		failure(c, 503, "upstream_uncertain")
		return
	}
	if status != 200 {
		failure(c, 403, "import_voice_not_found")
		return
	}
	parsed, pe := ParseQueryVoiceResponse(body)
	if pe != nil {
		failure(c, 403, "import_voice_unreadable")
		return
	}
	if parsed.TargetModel != "" && parsed.TargetModel != cap.Model {
		failure(c, 403, "import_model_mismatch")
		return
	}
	mapped, me := MapOfficialVoiceStatus(parsed.Status)
	if me != nil {
		failure(c, 403, "import_voice_unknown_status")
		return
	}
	now := time.Now().Unix()
	row := PrivateVoice{
		UserID: p.User.Id, VoiceID: req.Voice, Model: cap.Model, Region: cap.Region, ChannelID: channel.Id,
		Status: "pending_authorization", Kind: "import", TaskID: uuid.NewString(),
		PayloadHash: hash(raw), GrantSource: "import_unproven", AllowUse: false, AllowDelete: false,
		UpstreamStatus: parsed.Status, UpstreamRequestID: parsed.RequestID,
		CreatedAt: now, UpdatedAt: now, Error: "awaiting_admin_grant:" + mapped,
	}
	if e = g.DB.Create(&row).Error; e != nil {
		failure(c, 503, "voice_persist_failed")
		return
	}
	c.JSON(200, voiceView(g.DB, &row, false))
}

func (g *Gateway) VoiceDelete(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	// Wildcard captures dotted official IDs (qwen-audio-3.0-tts-plus-vd-...).
	voice := strings.TrimPrefix(c.Param("voice"), "/")
	if !validVoiceID(voice) {
		failure(c, 400, "invalid_voice")
		return
	}
	var row PrivateVoice
	if e := g.DB.Where("voice_id = ? AND user_id = ?", voice, p.User.Id).Take(&row).Error; e != nil {
		failure(c, 404, "voice_not_found")
		return
	}
	if !row.AllowDelete {
		failure(c, 403, "delete_not_authorized")
		return
	}
	cap, e := loadCapability(g.DB, row.Model, row.regionOrDefault(), "/api-ws/v1/inference")
	if e != nil {
		failure(c, 403, "model_not_allowed_or_not_verified")
		return
	}
	channel, e := SelectChannelByID(g.DB, p, cap, row.ChannelID)
	if e != nil {
		failure(c, 403, "channel_mismatch")
		return
	}
	upBody, e := BuildDeleteVoice(voice)
	if e != nil {
		failure(c, 400, "invalid_voice")
		return
	}
	upURL, e := UpstreamHTTP(*channel.BaseURL, "POST", HTTPPathCustomization)
	if e != nil {
		failure(c, 500, "upstream_configuration_error")
		return
	}
	status, _, err := g.proxyUpstream(c.Request.Context(), "POST", upURL, channel.Key, upBody)
	if err != nil || status == 429 || status >= 500 {
		row.Status, row.Error = "uncertain", "delete_uncertain"
		row.UpdatedAt = time.Now().Unix()
		_ = g.DB.Save(&row).Error
		c.JSON(200, gin.H{"status": "uncertain", "voice_id": voice})
		return
	}
	if status < 200 || status >= 300 {
		failure(c, 502, "upstream_delete_rejected")
		return
	}
	if e = g.DB.Delete(&row).Error; e != nil {
		failure(c, 503, "voice_delete_persist_failed")
		return
	}
	c.JSON(200, gin.H{"status": "deleted", "voice_id": voice})
}

func (g *Gateway) VoiceAdminGrant(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	if p.User.Role < model.RoleAdminUser {
		failure(c, 403, "administrator_required")
		return
	}
	raw, e := io.ReadAll(io.LimitReader(c.Request.Body, 16*1024))
	if e != nil {
		failure(c, 400, "invalid_json")
		return
	}
	var req struct {
		VoiceID      string `json:"voice_id"`
		TargetUserID int    `json:"target_user_id"`
		Reason       string `json:"reason"`
		AllowUse     bool   `json:"allow_use"`
		AllowDelete  bool   `json:"allow_delete"`
		Model        string `json:"model"`
		Region       string `json:"region"`
	}
	if strictJSON(raw, &req) != nil || !validVoiceID(req.VoiceID) || req.TargetUserID <= 0 || strings.TrimSpace(req.Reason) == "" {
		failure(c, 400, "grant_fields_required")
		return
	}
	region := req.Region
	if region == "" {
		region = "cn-beijing"
	}
	modelName := req.Model
	if modelName == "" {
		modelName = TargetTTSPlus
	}
	var row PrivateVoice
	e = g.DB.Where("voice_id = ? AND user_id = ? AND model = ?", req.VoiceID, req.TargetUserID, modelName).Take(&row).Error
	if errors.Is(e, gorm.ErrRecordNotFound) {
		failure(c, 404, "import_row_required")
		return
	}
	if e != nil {
		failure(c, 503, "database_unavailable")
		return
	}
	prev := row.UserID
	row.AllowUse = req.AllowUse
	row.AllowDelete = req.AllowDelete
	row.GrantedBy = p.User.Id
	row.GrantReason = req.Reason
	row.GrantSource = "admin_grant"
	if req.AllowUse && row.UpstreamStatus == StatusOK {
		row.Status = "available"
		row.Error = ""
	} else if req.AllowUse {
		row.Status = "pending_authorization"
		row.Error = "upstream_not_ok"
	}
	row.UpdatedAt = time.Now().Unix()
	if e = g.DB.Save(&row).Error; e != nil {
		failure(c, 503, "voice_persist_failed")
		return
	}
	_ = g.DB.Create(&model.BailianAudit{
		BillID: "voice-grant-" + row.TaskID, ActorID: p.User.Id, Action: "voice_grant",
		Reason:    req.Reason + ";prev_user=" + itoa10(prev) + ";target=" + itoa10(req.TargetUserID),
		CreatedAt: time.Now().Unix(),
	}).Error
	c.JSON(200, voiceView(g.DB, &row, false))
}

func allowedMediaURL(raw string) bool {
	u, e := url.Parse(raw)
	if e != nil || u.User != nil || u.Fragment != "" || u.RawQuery != "" {
		return false
	}
	if !strings.Contains(u.Path, "/official-tts/internal/media/") {
		return false
	}
	host, _, err := net.SplitHostPort(u.Host)
	if err != nil {
		host = u.Host
	}
	if testUpstreamEnabled() {
		return (u.Scheme == "http" || u.Scheme == "https") && (host == "127.0.0.1" || host == "localhost" || host == "::1")
	}
	if u.Scheme != "https" || host == "127.0.0.1" || host == "localhost" || host == "::1" {
		return false
	}
	for _, extra := range strings.Split(os.Getenv("BAILIAN_MEDIA_HOSTS"), ",") {
		if strings.TrimSpace(extra) != "" && host == strings.TrimSpace(extra) {
			return true
		}
	}
	return false
}

func (g *Gateway) proxyUpstream(ctx context.Context, method, rawURL, key string, body []byte) (int, []byte, error) {
	var rdr io.Reader
	if body != nil {
		rdr = bytes.NewReader(body)
	}
	req, e := http.NewRequestWithContext(ctx, method, rawURL, rdr)
	if e != nil {
		return 0, nil, e
	}
	req.Header.Set("Authorization", "Bearer "+key)
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 20 * time.Second}
	resp, e := client.Do(req)
	if e != nil {
		return 0, nil, e
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 2*1024*1024))
	return resp.StatusCode, data, nil
}

func (g *Gateway) reserveHTTP(p Principal, cap Capability, preset model.Channel, scope, payloadHash, op string, units int64) (model.Channel, Price, *model.BailianBill, int64, string) {
	unit := "count"
	if op == "synthesize" || op == "preview" {
		unit = "weighted_character"
	}
	price, mode, e := SnapshotOpPrice(g.DB, p, cap, op, unit)
	if e != nil {
		return model.Channel{}, Price{}, nil, 0, "operation_price_unconfigured"
	}
	if mode == ChargeFree {
		return model.Channel{}, Price{}, nil, 0, "free_operation_has_no_reserve"
	}
	if units <= 0 {
		return model.Channel{}, Price{}, nil, 0, "reservation_failed"
	}
	channel := preset
	if channel.Id == 0 {
		channel, e = SelectChannel(g.DB, p, cap)
		if e != nil {
			return model.Channel{}, Price{}, nil, 0, "channel_unavailable"
		}
	}
	amount, e := price.Quota(units, 1)
	if e != nil || amount <= 0 {
		return model.Channel{}, Price{}, nil, 0, "reservation_failed"
	}
	bill := &model.BailianBill{
		ID: uuid.NewString(), Scope: scope, PayloadHash: payloadHash,
		UserID: p.User.Id, TokenID: p.Token.Id, ChannelID: channel.Id,
		Model: cap.Model, Group: p.User.Group, PriceSnapshot: mustJSON(price),
	}
	reused, e := model.ReserveBailian(g.DB, bill, amount)
	if e != nil {
		if errors.Is(e, model.ErrBLQuota) {
			return model.Channel{}, Price{}, nil, 0, "insufficient_quota"
		}
		return model.Channel{}, Price{}, nil, 0, "reservation_failed"
	}
	if reused && bill.PayloadHash != payloadHash {
		return model.Channel{}, Price{}, nil, 0, "idempotency_payload_conflict"
	}
	if bill.Held <= 0 && bill.State == model.BLReserved {
		return model.Channel{}, Price{}, nil, 0, "reservation_failed"
	}
	return channel, price, bill, amount, ""
}

func mustJSON(v interface{}) string {
	b, _ := json.Marshal(v)
	return string(b)
}

func upstreamRejectReason(body []byte) string {
	var raw struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	}
	if json.Unmarshal(body, &raw) != nil {
		return ""
	}
	msg := strings.TrimSpace(raw.Message)
	if msg == "" {
		return ""
	}
	if len([]rune(msg)) > 200 {
		msg = string([]rune(msg)[:200])
	}
	return msg
}

func (g *Gateway) authorizePrivateOrCatalog(p Principal, cap Capability, voice string) (model.Channel, error) {
	if listHas(cap.Voices, voice) {
		return SelectChannel(g.DB, p, cap)
	}
	var row PrivateVoice
	if e := g.DB.Where("voice_id = ? AND user_id = ? AND model = ?", voice, p.User.Id, cap.Model).Take(&row).Error; e != nil {
		return model.Channel{}, errors.New("voice_not_authorized")
	}
	if row.Status != "available" || !row.AllowUse {
		return model.Channel{}, errors.New("voice_not_authorized")
	}
	if row.Region != "" && row.Region != cap.Region {
		return model.Channel{}, errors.New("voice_region_mismatch")
	}
	return SelectChannelByID(g.DB, p, cap, row.ChannelID)
}
