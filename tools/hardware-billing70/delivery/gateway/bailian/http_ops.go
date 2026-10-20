package bailian

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm"
)

type synthCanon struct {
	Model           string   `json:"model"`
	Voice           string   `json:"voice"`
	Text            string   `json:"text"`
	Format          string   `json:"format"`
	SampleRate      int      `json:"sample_rate"`
	Volume          *int     `json:"volume"`
	Rate            *float64 `json:"rate"`
	Pitch           *float64 `json:"pitch"`
	Instruction     string   `json:"instruction"`
	LanguageHints   []string `json:"language_hints"`
	HotFix          string   `json:"hot_fix"`
	EnableAIGC      bool     `json:"enable_aigc_tag"`
	AIGCPropagator  string   `json:"aigc_propagator"`
	AIGCPropagateID string   `json:"aigc_propagate_id"`
	BitRate         *int     `json:"bit_rate"`
	EnableSSML      bool     `json:"enable_ssml"`
	Operation       string   `json:"operation"`
}

func (g *Gateway) HTTPSynthesis(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	raw, e := io.ReadAll(io.LimitReader(c.Request.Body, 256*1024))
	if e != nil {
		failure(c, 400, "invalid_json")
		return
	}
	var req struct {
		Model           string          `json:"model"`
		Voice           string          `json:"voice"`
		Text            string          `json:"text"`
		Format          string          `json:"format"`
		SampleRate      int             `json:"sample_rate"`
		Volume          *int            `json:"volume,omitempty"`
		Rate            *float64        `json:"rate,omitempty"`
		Pitch           *float64        `json:"pitch,omitempty"`
		Instruction     string          `json:"instruction,omitempty"`
		LanguageHints   []string        `json:"language_hints,omitempty"`
		HotFix          json.RawMessage `json:"hot_fix,omitempty"`
		EnableAIGC      bool            `json:"enable_aigc_tag,omitempty"`
		AIGCPropagator  string          `json:"aigc_propagator,omitempty"`
		AIGCPropagateID string          `json:"aigc_propagate_id,omitempty"`
		BitRate         *int            `json:"bit_rate,omitempty"`
		EnableSSML      bool            `json:"enable_ssml,omitempty"`
		Idempotency     string          `json:"idempotency_key,omitempty"`
		Operation       string          `json:"operation,omitempty"`
		Region          string          `json:"region,omitempty"`
	}
	if strictJSON(raw, &req) != nil || req.Model == "" || req.Text == "" || req.Voice == "" {
		failure(c, 400, "invalid_synthesis")
		return
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
	op := req.Operation
	if op == "" {
		op = "synthesize"
	}
	if op != "synthesize" && op != "preview" {
		failure(c, 400, "invalid_operation")
		return
	}
	channel, e := g.authorizePrivateOrCatalog(p, cap, req.Voice)
	if e != nil {
		failure(c, 403, "voice_not_authorized")
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
	synthReq := SpeechSynthRequest{
		Model: cap.Model, Voice: req.Voice, Text: req.Text, Format: req.Format,
		SampleRate: req.SampleRate, Volume: req.Volume, Rate: req.Rate, Pitch: req.Pitch,
		Instruction: req.Instruction, LanguageHints: req.LanguageHints, HotFix: req.HotFix,
		EnableAIGC: req.EnableAIGC, AIGCPropagator: req.AIGCPropagator, AIGCPropagateID: req.AIGCPropagateID,
		BitRate: req.BitRate, EnableSSML: req.EnableSSML,
	}
	if e := synthReq.Validate(); e != nil {
		failure(c, 400, e.Error())
		return
	}
	hot := ""
	if len(req.HotFix) > 0 {
		canonHF, e := CanonicalHotFixJSON(req.HotFix)
		if e != nil {
			failure(c, 400, e.Error())
			return
		}
		synthReq.HotFix = canonHF
		hot = string(canonHF)
	}
	canon, _ := json.Marshal(synthCanon{
		Model: cap.Model, Voice: req.Voice, Text: req.Text, Format: req.Format,
		SampleRate: req.SampleRate, Volume: req.Volume, Rate: req.Rate, Pitch: req.Pitch,
		Instruction: req.Instruction, LanguageHints: req.LanguageHints,
		HotFix: hot, EnableAIGC: req.EnableAIGC, AIGCPropagator: req.AIGCPropagator,
		AIGCPropagateID: req.AIGCPropagateID, BitRate: req.BitRate, EnableSSML: req.EnableSSML,
		Operation: op,
	})
	payloadHash := hash(canon)
	scope := userScope("synth", op, p.User.Id, idem)
	unlock := g.lockScope(scope)
	defer unlock()
	var prior model.BailianBill
	resumeReserved := false
	if g.DB.Where("scope = ?", scope).Take(&prior).Error == nil {
		if prior.PayloadHash != payloadHash || prior.UserID != p.User.Id {
			failure(c, 409, "idempotency_payload_conflict")
			return
		}
		if prior.State != model.BLReserved {
			if prior.State == model.BLSubmitted {
				g.finishSubmittedIfArtifactComplete(&prior)
			}
			g.writeSynthResponse(c, &prior, payloadHash, true)
			return
		}
		resumeReserved = true
	}
	chars, e := synthReq.ReserveUnits()
	if e != nil || chars <= 0 {
		failure(c, 400, "meter_unavailable")
		return
	}
	// Isolation-only: after the HTTP task is accepted/metered but before ReserveBailian.
	// Recover must be allowed to reserve and call upstream once.
	isolationCrash("pre_reserve")
	var price Price
	var bill *model.BailianBill
	var amount int64
	if resumeReserved {
		price, _, e = SnapshotOpPrice(g.DB, p, cap, op, "weighted_character")
		if e != nil {
			failure(c, 403, "operation_price_unconfigured")
			return
		}
		bill = &prior
		amount = prior.Held
	} else {
		var errCode string
		_, price, bill, amount, errCode = g.reserveHTTP(p, cap, channel, scope, payloadHash, op, chars)
		if errCode != "" {
			code := 402
			if errCode == "idempotency_payload_conflict" {
				code = 409
			}
			if errCode == "operation_price_unconfigured" || errCode == "operation_disabled" {
				code = 403
			}
			failure(c, code, errCode)
			return
		}
		isolationCrash("reserved")
	}
	claimed, e := model.ClaimSubmitBailian(g.DB, bill.ID)
	if e != nil {
		failure(c, 503, "ledger_unavailable")
		return
	}
	if !claimed {
		g.writeSynthResponse(c, bill, payloadHash, true)
		return
	}
	isolationCrash("claimed")
	upURL, e := UpstreamHTTP(*channel.BaseURL, "POST", HTTPPathSpeechSynthesizer)
	if e != nil {
		_ = model.FinishBailian(g.DB, bill.ID, 0, true, 0, "upstream_configuration_error")
		failure(c, 500, "upstream_configuration_error")
		return
	}
	upBody, e := BuildSpeechSynthesizer(synthReq)
	if e != nil {
		_ = model.FinishBailian(g.DB, bill.ID, 0, false, 0, "invalid_synthesis")
		failure(c, 400, "invalid_synthesis")
		return
	}
	status, body, err := g.proxyUpstream(c.Request.Context(), "POST", upURL, channel.Key, upBody)
	isolationCrash("upstream_done")
	review := false
	reason := "completed"
	charged := int64(0)
	art := SynthArtifact{BillID: bill.ID, UserID: p.User.Id, PayloadHash: payloadHash, Format: req.Format, CreatedAt: time.Now().Unix()}
	if err != nil {
		review, reason = true, "upstream_uncertain"
		art.Status, art.Error = "uncertain", reason
	} else if status == 429 || status >= 500 {
		review, reason = true, "upstream_unavailable"
		art.Status, art.Error = "uncertain", reason
	} else if status < 200 || status >= 300 {
		reason = "upstream_rejected"
		art.Status, art.Error = "failed", reason
	} else {
		parsed, pe := ParseSpeechSynthesizerResponse(body)
		if pe != nil {
			review, reason = true, pe.Error()
			art.Status, art.Error = "uncertain", reason
		} else {
			audio, ae := g.materializeOfficialAudio(c, parsed)
			if ae != nil {
				review, reason = true, ae.Error()
				art.Status, art.Error = "uncertain", reason
			} else {
				ct, ie := InspectExportAudio(req.Format, audio)
				if ie != nil {
					review, reason = true, ie.Error()
					art.Status, art.Error = "uncertain", reason
				} else if parsed.Characters <= 0 {
					review, reason = true, "usage_characters_missing"
					art.Status, art.Error = "uncertain", reason
					_ = g.storeSynthAudio(&art, req.Format, ct, audio)
				} else {
					if q, qe := price.Quota(parsed.Characters, 1); qe == nil && q > 0 {
						charged = q
						if charged > amount {
							review, reason = true, "usage_exceeds_hold"
							charged = 0
						}
					} else {
						review, reason = true, "usage_unmeterable"
					}
					if e := g.storeSynthAudio(&art, req.Format, ct, audio); e != nil {
						review, reason = true, "audio_persist_failed"
						// Do not refund: upstream completed.
					} else {
						art.Status = "completed"
						art.Characters = parsed.Characters
					}
				}
			}
		}
	}
	_ = g.DB.Save(&art).Error
	isolationCrash("audio_stored")
	if e = model.FinishBailian(g.DB, bill.ID, charged, review, 0, reason); e != nil {
		review = true
	}
	isolationCrash("settled")
	_ = g.DB.Where("id = ?", bill.ID).Take(bill).Error
	g.writeSynthResponse(c, bill, payloadHash, false)
}

func (g *Gateway) finishSubmittedIfArtifactComplete(bill *model.BailianBill) {
	if bill == nil || bill.State != model.BLSubmitted {
		return
	}
	var art SynthArtifact
	if g.DB.Where("bill_id = ?", bill.ID).Take(&art).Error != nil {
		return
	}
	if art.Status != "completed" || art.Characters <= 0 {
		return
	}
	var price Price
	if json.Unmarshal([]byte(bill.PriceSnapshot), &price) != nil {
		return
	}
	charged, e := price.Quota(art.Characters, 1)
	if e != nil || charged <= 0 {
		return
	}
	if charged > bill.Held {
		_ = model.FinishBailian(g.DB, bill.ID, 0, true, 0, "usage_exceeds_hold")
	} else {
		_ = model.FinishBailian(g.DB, bill.ID, charged, false, 0, "completed")
	}
	_ = g.DB.Where("id = ?", bill.ID).Take(bill)
}

func (g *Gateway) writeSynthResponse(c *gin.Context, bill *model.BailianBill, payloadHash string, reused bool) {
	var art SynthArtifact
	_ = g.DB.Where("bill_id = ?", bill.ID).Take(&art).Error
	audio := ""
	if art.RelPath != "" {
		if raw, e := os.ReadFile(g.artifactPath(art.RelPath)); e == nil {
			audio = base64.StdEncoding.EncodeToString(raw)
		}
	}
	quota := bill.Charged
	if quota == 0 && bill.Held > 0 {
		quota = bill.Held
	}
	code := 200
	if !reused && art.Status == "failed" && bill.State == model.BLRefunded {
		code = 502
	}
	c.JSON(code, gin.H{
		"task_id": bill.ID, "bill_id": bill.ID, "status": art.Status,
		"bill_state": bill.State, "quota": quota, "reserved": bill.Held, "settled": bill.Charged,
		"review": bill.State == model.BLReview, "reused": reused,
		"audio": audio, "content_type": art.ContentType, "format": art.Format,
		"price_version": priceVersionOf(bill.PriceSnapshot),
	})
}

func priceVersionOf(snapshot string) string {
	var p Price
	_ = json.Unmarshal([]byte(snapshot), &p)
	return p.Version
}

func (g *Gateway) artifactDir() string {
	d := os.Getenv("BAILIAN_RESULT_DIR")
	if d == "" {
		d = filepath.Join(os.TempDir(), "bailian-results")
	}
	_ = os.MkdirAll(d, 0o750)
	return d
}

func (g *Gateway) artifactPath(rel string) string {
	return filepath.Join(g.artifactDir(), filepath.Base(rel))
}

func (g *Gateway) storeSynthAudio(art *SynthArtifact, format, ct string, audio []byte) error {
	if format == "" {
		format = "wav"
	}
	name := art.BillID + "." + format
	if e := os.WriteFile(g.artifactPath(name), audio, 0o640); e != nil {
		return e
	}
	art.RelPath = name
	art.Format = format
	art.ContentType = ct
	return nil
}

func (g *Gateway) materializeOfficialAudio(c *gin.Context, parsed OfficialSynthOut) ([]byte, error) {
	if parsed.AudioData != "" {
		return DecodeOfficialAudio(parsed)
	}
	if parsed.AudioURL == "" {
		return nil, errors.New("official_synth_missing_audio")
	}
	if !allowedAudioFetchURL(parsed.AudioURL) {
		return nil, errors.New("audio_url_not_allowed:" + audioURLSchemeHost(parsed.AudioURL))
	}
	req, e := http.NewRequestWithContext(c.Request.Context(), "GET", parsed.AudioURL, nil)
	if e != nil {
		return nil, e
	}
	if e := audioFetchResolvedOK(parsed.AudioURL); e != nil {
		return nil, e
	}
	client := &http.Client{
		Timeout: 20 * time.Second,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 3 {
				return errors.New("redirect_blocked")
			}
			if !allowedAudioFetchURL(req.URL.String()) {
				return errors.New("redirect_blocked")
			}
			return audioFetchResolvedOK(req.URL.String())
		},
	}
	resp, e := client.Do(req)
	if e != nil {
		return nil, e
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, errors.New("audio_url_fetch_failed")
	}
	return io.ReadAll(io.LimitReader(resp.Body, 8*1024*1024))
}

func audioURLSchemeHost(raw string) string {
	u, e := url.Parse(raw)
	if e != nil {
		return "unparsed"
	}
	host, _, err := net.SplitHostPort(u.Host)
	if err != nil {
		host = u.Host
	}
	if host == "" {
		host = "empty"
	}
	return u.Scheme + ":" + host
}

func audioURLHost(u *url.URL) string {
	host, _, err := net.SplitHostPort(u.Host)
	if err != nil {
		return u.Host
	}
	return host
}

func audioFetchExplicitPortOK(scheme, hostport string) bool {
	_, port, err := net.SplitHostPort(hostport)
	if err != nil {
		return true
	}
	switch scheme {
	case "http":
		return port == "80"
	case "https":
		return port == "443"
	default:
		return false
	}
}

func audioURLHostIsLoopback(host string) bool {
	return host == "127.0.0.1" || host == "localhost" || host == "::1"
}

func officialDashscopeOSSHost(host string) bool {
	h := strings.ToLower(strings.TrimSpace(host))
	if h == "" || strings.Contains(h, "internal") || strings.Contains(h, "vpc") {
		return false
	}
	labels := strings.Split(h, ".")
	if len(labels) < 4 {
		return false
	}
	if labels[len(labels)-2] != "aliyuncs" || labels[len(labels)-1] != "com" {
		return false
	}
	if !strings.HasPrefix(labels[0], "dashscope-result-") || len(labels[0]) <= len("dashscope-result-") {
		return false
	}
	hasOSS := false
	for _, lab := range labels[1 : len(labels)-2] {
		if strings.HasPrefix(lab, "oss-") && !strings.Contains(lab, "internal") {
			hasOSS = true
		}
	}
	return hasOSS
}

func resolvedAudioHostPublic(host string) bool {
	ips, err := net.LookupIP(host)
	if err != nil || len(ips) == 0 {
		return false
	}
	for _, ip := range ips {
		if ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || ip.IsUnspecified() || ip.IsMulticast() {
			return false
		}
	}
	return true
}

func allowedAudioFetchURL(raw string) bool {
	u, e := url.Parse(raw)
	if e != nil || u.User != nil || u.Fragment != "" {
		return false
	}
	host := audioURLHost(u)
	if u.Scheme != "http" && u.Scheme != "https" {
		return false
	}
	if testUpstreamEnabled() && audioURLHostIsLoopback(host) {
		return true
	}
	if !audioFetchExplicitPortOK(u.Scheme, u.Host) {
		return false
	}
	// Official non-stream SpeechSynthesizer returns http://dashscope-result-*.oss-*.aliyuncs.com.
	// Do not allow arbitrary *.aliyuncs.com (RAM/ECS/internal OSS/VPC).
	return officialDashscopeOSSHost(host)
}

func audioFetchResolvedOK(raw string) error {
	u, e := url.Parse(raw)
	if e != nil {
		return errors.New("audio_url_not_allowed:unparsed")
	}
	host := audioURLHost(u)
	if testUpstreamEnabled() && audioURLHostIsLoopback(host) {
		return nil
	}
	if !resolvedAudioHostPublic(host) {
		return errors.New("audio_url_resolved_private:" + audioURLSchemeHost(raw))
	}
	return nil
}

func (g *Gateway) HTTPCancel(c *gin.Context) {
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
		BillID string `json:"bill_id"`
		TaskID string `json:"task_id"`
	}
	if strictJSON(raw, &req) != nil {
		failure(c, 400, "invalid_cancel")
		return
	}
	id := req.BillID
	if id == "" {
		id = req.TaskID
	}
	if id == "" {
		failure(c, 400, "bill_required")
		return
	}
	var bill model.BailianBill
	if e := g.DB.Where("id = ? AND user_id = ?", id, p.User.Id).Take(&bill).Error; e != nil {
		failure(c, 404, "bill_not_found")
		return
	}
	switch bill.State {
	case model.BLReserved:
		if e = model.FinishBailian(g.DB, bill.ID, 0, false, 0, "cancelled_before_submit"); e != nil {
			failure(c, 503, "ledger_unavailable")
			return
		}
		c.JSON(200, gin.H{"status": "released", "bill_id": bill.ID, "reserved": 0, "settled": 0})
	case model.BLSubmitted:
		if e = model.FinishBailian(g.DB, bill.ID, bill.Charged, true, 0, "cancelled_after_submit"); e != nil {
			failure(c, 503, "ledger_unavailable")
			return
		}
		c.JSON(200, gin.H{"status": "uncertain", "bill_id": bill.ID, "reserved": bill.Held, "settled": bill.Charged})
	case model.BLSettled:
		c.JSON(200, gin.H{"status": "already_settled", "bill_id": bill.ID, "reserved": bill.Held, "settled": bill.Charged})
	default:
		c.JSON(200, gin.H{"status": bill.State, "bill_id": bill.ID, "idempotent": true, "reserved": bill.Held, "settled": bill.Charged})
	}
}

func (g *Gateway) adminPrincipal(c *gin.Context) (Principal, bool) {
	p, ok := g.httpAuth(c)
	if !ok {
		return p, false
	}
	if p.User.Role < model.RoleAdminUser {
		failure(c, 403, "administrator_required")
		return p, false
	}
	return p, true
}

func (g *Gateway) AdminGetBill(c *gin.Context) {
	p, ok := g.adminPrincipal(c)
	if !ok {
		return
	}
	_ = p
	id := c.Param("id")
	var bill model.BailianBill
	if g.DB.Where("id = ?", id).Take(&bill).Error != nil {
		failure(c, 404, "bill_not_found")
		return
	}
	var user model.User
	_ = g.DB.Select("id", "username", "quota", "used_quota", "status").First(&user, bill.UserID).Error
	var token model.Token
	_ = g.DB.Select("id", "remain_quota", "used_quota", "unlimited_quota", "status").First(&token, bill.TokenID).Error
	deltaCharge := int64(0)
	deltaRelease := bill.Held
	c.JSON(200, gin.H{
		"bill_id": bill.ID, "user_id": bill.UserID, "token_id": bill.TokenID,
		"state": bill.State, "held": bill.Held, "charged": bill.Charged,
		"model": bill.Model, "price_snapshot": bill.PriceSnapshot,
		"reason": bill.Reason, "created_at": bill.CreatedAt, "updated_at": bill.UpdatedAt,
		"user_quota": user.Quota, "user_used_quota": user.UsedQuota,
		"token_remain_quota": token.RemainQuota, "token_used_quota": token.UsedQuota,
		"preview_if_final_equals_charged": gin.H{
			"additional_charge": deltaCharge, "release": deltaRelease,
			"note": "final_total is cumulative charged, not an increment",
		},
	})
}

func (g *Gateway) AdminNote(c *gin.Context) {
	p, ok := g.adminPrincipal(c)
	if !ok {
		return
	}
	id := c.Param("id")
	raw, e := io.ReadAll(io.LimitReader(c.Request.Body, 16*1024))
	if e != nil {
		failure(c, 400, "invalid_json")
		return
	}
	var req struct {
		Reason   string `json:"reason"`
		Evidence string `json:"evidence"`
		OpID     string `json:"operation_id"`
	}
	if strictJSON(raw, &req) != nil || strings.TrimSpace(req.Reason) == "" || strings.TrimSpace(req.OpID) == "" {
		failure(c, 400, "note_reason_and_operation_id_required")
		return
	}
	var bill model.BailianBill
	if g.DB.Where("id = ?", id).Take(&bill).Error != nil {
		failure(c, 404, "bill_not_found")
		return
	}
	now := time.Now().Unix()
	op := model.BailianAdminOp{
		OperationID: req.OpID, BillID: id, Kind: "note", ActorID: p.User.Id,
		Reason: req.Reason, Evidence: req.Evidence,
		BeforeHeld: bill.Held, BeforeCharged: bill.Charged,
		AfterHeld: bill.Held, AfterCharged: bill.Charged, State: bill.State, CreatedAt: now,
	}
	e = g.DB.Transaction(func(tx *gorm.DB) error {
		var existing model.BailianAdminOp
		found := tx.Where("operation_id = ?", req.OpID).Take(&existing).Error
		if found == nil {
			if existing.BillID != id || existing.Kind != "note" {
				return model.ErrBLConflict
			}
			op = existing
			return nil
		}
		if e := tx.Create(&op).Error; e != nil {
			return e
		}
		return tx.Create(&model.BailianAudit{
			BillID: id, ActorID: p.User.Id, Action: "admin_note",
			Reason: req.Reason + " | " + req.Evidence, CreatedAt: now,
		}).Error
	})
	if e != nil {
		failure(c, 409, "note_conflict")
		return
	}
	c.JSON(200, gin.H{
		"bill_id": id, "state": bill.State, "charged": bill.Charged, "held": bill.Held,
		"actor_id": p.User.Id, "operation_id": req.OpID, "kind": "note",
		"funds_changed": false,
	})
}

func (g *Gateway) AdminResolve(c *gin.Context) {
	p, ok := g.adminPrincipal(c)
	if !ok {
		return
	}
	id := c.Param("id")
	if strings.HasPrefix(id, "mem_") {
		failure(c, 409, "memory_resolution_endpoint_required")
		return
	}
	raw, e := io.ReadAll(io.LimitReader(c.Request.Body, 16*1024))
	if e != nil {
		failure(c, 400, "invalid_json")
		return
	}
	var req struct {
		FinalTotal  *int64 `json:"final_total"`
		ConfirmZero bool   `json:"confirm_zero"`
		Review      bool   `json:"review"`
		Reason      string `json:"reason"`
		Evidence    string `json:"evidence"`
		OpID        string `json:"operation_id"`
	}
	if strictJSON(raw, &req) != nil {
		failure(c, 400, "invalid_json")
		return
	}
	if strings.TrimSpace(req.OpID) == "" {
		failure(c, 400, "operation_id_required")
		return
	}
	if strings.TrimSpace(req.Reason) == "" || strings.TrimSpace(req.Evidence) == "" {
		failure(c, 400, "admin_reason_and_evidence_required")
		return
	}
	if req.FinalTotal == nil {
		failure(c, 400, "final_total_required")
		return
	}
	finalTotal := *req.FinalTotal
	if finalTotal < 0 {
		failure(c, 400, "final_total_invalid")
		return
	}
	if finalTotal == 0 && !req.ConfirmZero {
		failure(c, 400, "confirm_zero_required")
		return
	}
	if req.Review {
		failure(c, 400, "admin_settle_must_not_keep_review")
		return
	}
	var existing model.BailianAdminOp
	if g.DB.Where("operation_id = ?", req.OpID).Take(&existing).Error == nil {
		if existing.BillID != id || existing.Kind != "settle" || existing.FinalTotal != finalTotal || existing.ConfirmZero != req.ConfirmZero {
			failure(c, 409, "operation_id_conflict")
			return
		}
		c.JSON(200, gin.H{
			"bill_id": id, "state": existing.State, "charged": existing.AfterCharged, "held": existing.AfterHeld,
			"actor_id": existing.ActorID, "reason": existing.Reason, "operation_id": existing.OperationID,
			"before_charged": existing.BeforeCharged, "before_held": existing.BeforeHeld,
			"additional_charge": existing.AfterCharged - existing.BeforeCharged,
			"released":          existing.BeforeHeld - existing.AfterHeld,
			"reused":            true, "final_total_is_cumulative": true,
		})
		return
	}
	var bill model.BailianBill
	if g.DB.Where("id = ?", id).Take(&bill).Error != nil {
		failure(c, 404, "bill_not_found")
		return
	}
	if finalTotal < bill.Charged {
		failure(c, 409, "cannot_reduce_below_confirmed")
		return
	}
	beforeHeld, beforeCharged := bill.Held, bill.Charged
	if e = model.FinishBailian(g.DB, id, finalTotal, false, p.User.Id, req.Reason); e != nil {
		failure(c, 409, "billing_conflict")
		return
	}
	_ = g.DB.Where("id = ?", id).Take(&bill).Error
	op := model.BailianAdminOp{
		OperationID: req.OpID, BillID: id, Kind: "settle", FinalTotal: finalTotal,
		ConfirmZero: req.ConfirmZero, ActorID: p.User.Id, Reason: req.Reason, Evidence: req.Evidence,
		BeforeHeld: beforeHeld, BeforeCharged: beforeCharged,
		AfterHeld: bill.Held, AfterCharged: bill.Charged, State: bill.State, CreatedAt: time.Now().Unix(),
	}
	if e = g.DB.Create(&op).Error; e != nil {
		var again model.BailianAdminOp
		if g.DB.Where("operation_id = ?", req.OpID).Take(&again).Error == nil && again.BillID == id && again.Kind == "settle" && again.FinalTotal == finalTotal {
			c.JSON(200, gin.H{
				"bill_id": id, "state": again.State, "charged": again.AfterCharged, "held": again.AfterHeld,
				"actor_id": again.ActorID, "reason": again.Reason, "operation_id": again.OperationID,
				"before_charged": again.BeforeCharged, "before_held": again.BeforeHeld,
				"additional_charge": again.AfterCharged - again.BeforeCharged,
				"released":          again.BeforeHeld - again.AfterHeld,
				"reused":            true, "final_total_is_cumulative": true,
			})
			return
		}
		failure(c, 503, "operation_record_failed")
		return
	}
	c.JSON(200, gin.H{
		"bill_id": id, "state": bill.State, "charged": bill.Charged, "held": bill.Held,
		"actor_id": p.User.Id, "reason": req.Reason, "operation_id": req.OpID,
		"before_charged": beforeCharged, "before_held": beforeHeld,
		"additional_charge": bill.Charged - beforeCharged,
		"released":          beforeHeld - bill.Held,
		"reused":            false, "final_total_is_cumulative": true,
		"resolved_at": time.Now().Unix(),
	})
}

func (g *Gateway) PublishPrices(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	if p.User.Role < model.RoleAdminUser {
		failure(c, 403, "administrator_required")
		return
	}
	raw, e := io.ReadAll(io.LimitReader(c.Request.Body, 64*1024))
	if e != nil {
		failure(c, 400, "invalid_json")
		return
	}
	var box struct {
		Prices []SalePriceSpec `json:"prices"`
		Reason string          `json:"reason"`
	}
	if json.Unmarshal(raw, &box) != nil {
		failure(c, 400, "invalid_json")
		return
	}
	if len(box.Prices) == 0 {
		var one SalePriceSpec
		if strictJSON(raw, &one) != nil || one.Operation == "" {
			failure(c, 400, "price_specs_required")
			return
		}
		box.Prices = []SalePriceSpec{one}
	}
	published := make([]OperationPrice, 0, len(box.Prices))
	e = g.DB.Transaction(func(tx *gorm.DB) error {
		for i := range box.Prices {
			if box.Prices[i].Reason == "" {
				box.Prices[i].Reason = box.Reason
			}
			row, err := PublishSalePrice(tx, p.User.Id, box.Prices[i])
			if err != nil {
				return err
			}
			published = append(published, row)
		}
		return nil
	})
	if e != nil {
		failure(c, 409, e.Error())
		return
	}
	versions := make([]string, 0, len(published))
	for _, row := range published {
		versions = append(versions, row.Version)
	}
	c.JSON(200, gin.H{
		"status": "published", "ack": true, "versions": versions, "prices": published,
		"actor_id": p.User.Id,
	})
}

func (g *Gateway) PublishedPrices(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	if p.User.Role < model.RoleAdminUser {
		failure(c, 403, "administrator_required")
		return
	}
	var rows []OperationPrice
	q := g.DB.Where("kind = ?", PriceKindSale)
	if c.Query("history") != "1" {
		q = q.Where("enabled = ?", true)
	}
	if c.Query("model") != "" {
		q = q.Where("model = ?", c.Query("model"))
	}
	if c.Query("operation") != "" {
		q = q.Where("operation = ?", c.Query("operation"))
	}
	if e := q.Order("operation ASC").Find(&rows).Error; e != nil {
		failure(c, 503, "database_unavailable")
		return
	}
	c.JSON(200, gin.H{"prices": rows})
}
