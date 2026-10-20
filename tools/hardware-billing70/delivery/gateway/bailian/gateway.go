package bailian

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm"
)

type Gateway struct {
	DB               *gorm.DB
	Context          context.Context
	mu               sync.Mutex
	users            map[int]int
	total            int
	wg               sync.WaitGroup
	scopes           sync.Map
	memoryRateMu     sync.Mutex
	memoryRateMinute int64
	memoryRateTotal  int
	memoryRateAdd    int
	memoryRateSearch int
}

func NewGateway(ctx context.Context, db *gorm.DB) *Gateway {
	return &Gateway{DB: db, Context: ctx, users: map[int]int{}}
}
func (g *Gateway) Wait() { g.wg.Wait() }
func (g *Gateway) acquire(id int) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.Context.Err() != nil || g.total >= 16 || g.users[id] >= 4 {
		return false
	}
	g.total++
	g.users[id]++
	g.wg.Add(1)
	return true
}
func (g *Gateway) release(id int) {
	g.mu.Lock()
	g.total--
	g.users[id]--
	if g.users[id] == 0 {
		delete(g.users, id)
	}
	g.mu.Unlock()
	g.wg.Done()
}
func (g *Gateway) Routes(r *gin.Engine) {
	r.GET("/bailian/api-ws/v1/inference", g.Inference)
	for _, p := range []string{"/v1/realtime", "/v1/audio/realtime", "/bailian/api-ws/v1/realtime"} {
		r.GET(p, g.Realtime)
	}
	r.POST("/bailian/v1/voices/clone", g.VoiceClone)
	r.POST("/bailian/v1/voices/design", g.VoiceDesign)
	r.GET("/bailian/v1/voices/tasks/:id", g.VoiceTask)
	r.POST("/bailian/v1/voices/import", g.VoiceImport)
	r.POST("/bailian/v1/voices/admin-grant", g.VoiceAdminGrant)
	r.DELETE("/bailian/v1/voices/*voice", g.VoiceDelete)
	r.GET("/bailian/v1/voices", g.VoiceList)
	r.POST("/bailian/v1/synthesis", g.HTTPSynthesis)
	r.POST("/bailian/v1/synthesis/cancel", g.HTTPCancel)
	r.GET("/bailian/v1/bills/:id", g.AdminGetBill)
	r.POST("/bailian/v1/bills/:id/admin-note", g.AdminNote)
	r.POST("/bailian/v1/bills/:id/admin-resolve", g.AdminResolve)
	r.POST("/bailian/v1/memory/operations/:id/admin-resolve", g.AdminMemoryResolve)
	r.POST("/bailian/v1/prices/publish", g.PublishPrices)
	r.GET("/bailian/v1/prices/published", g.PublishedPrices)
	// No wildcard upstream proxy: unknown native HTTP routes stay closed.
}
func failure(c *gin.Context, status int, code string) {
	c.AbortWithStatusJSON(status, gin.H{"error": gin.H{"code": code, "type": "bailian_gateway_error"}})
}
func socketFailure(c *websocket.Conn, code string) {
	payload, _ := json.Marshal(gin.H{"type": "error", "error": gin.H{"code": code}})
	_ = socketWrite(c, 1, payload)
	_ = c.WriteControl(websocket.CloseMessage, websocket.FormatCloseMessage(1008, code), time.Now().Add(time.Second))
}
func socketWrite(c *websocket.Conn, kind int, data []byte) error {
	_ = c.SetWriteDeadline(time.Now().Add(5 * time.Second))
	return c.WriteMessage(kind, data)
}
func hash(data []byte) string { h := sha256.Sum256(data); return hex.EncodeToString(h[:]) }

func (g *Gateway) lockScope(scope string) func() {
	v, _ := g.scopes.LoadOrStore(scope, &sync.Mutex{})
	m := v.(*sync.Mutex)
	m.Lock()
	return func() { m.Unlock() }
}

func (g *Gateway) preflight(c *gin.Context) (Principal, bool) {
	if c.GetHeader("Origin") != "" {
		failure(c, 403, "server_to_server_only")
		return Principal{}, false
	}
	if !websocket.IsWebSocketUpgrade(c.Request) {
		failure(c, 426, "websocket_required")
		return Principal{}, false
	}
	for key := range c.Request.URL.Query() {
		if key != "model" {
			failure(c, 400, "query_parameter_not_allowed")
			return Principal{}, false
		}
	}
	if len(c.Request.URL.Query()["model"]) > 1 {
		failure(c, 400, "ambiguous_model")
		return Principal{}, false
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
	defer cancel()
	p, e := Authenticate(g.DB.WithContext(ctx), c.Request, c.ClientIP())
	if e != nil {
		log.Printf("bailian authentication rejected: %s", e.Error())
		failure(c, 401, "authentication_failed")
		return p, false
	}
	if !g.acquire(p.User.Id) {
		failure(c, 429, "session_limit")
		return p, false
	}
	return p, true
}
func upgrade(c *gin.Context) (*websocket.Conn, error) {
	u := websocket.Upgrader{HandshakeTimeout: 5 * time.Second}
	ws, e := u.Upgrade(c.Writer, c.Request, nil)
	if e == nil {
		ws.SetReadLimit(MaxFrame)
	}
	return ws, e
}

func (g *Gateway) Inference(c *gin.Context) {
	p, ok := g.preflight(c)
	if !ok {
		return
	}
	defer g.release(p.User.Id)
	client, e := upgrade(c)
	if e != nil {
		return
	}
	defer client.Close()
	_ = client.SetReadDeadline(time.Now().Add(10 * time.Second))
	kind, data, e := client.ReadMessage()
	if e != nil || kind != 1 {
		socketFailure(client, "run_task_required")
		return
	}
	ev, e := ParseRun(data)
	if e != nil {
		socketFailure(client, "invalid_run_task")
		return
	}
	if c.Query("model") != "" && c.Query("model") != ev.Payload.Model {
		socketFailure(client, "model_mismatch")
		return
	}
	cap, e := loadCapability(g.DB, ev.Payload.Model, "cn-beijing", "/api-ws/v1/inference")
	if e != nil || !p.Allows(ev.Payload.Model, cap.Model) {
		socketFailure(client, "model_not_allowed_or_not_verified")
		return
	}
	ev.Payload.Model = cap.Model
	extras := ListPrivateVoiceIDs(g.DB, p.User.Id, cap.Model)
	state, e := ConfigureTask(ev, cap, extras)
	if e != nil {
		socketFailure(client, "invalid_task_configuration")
		return
	}
	channel, e := g.authorizePrivateOrCatalog(p, cap, state.Voice)
	if e != nil {
		socketFailure(client, "voice_not_authorized")
		return
	}
	price, mode, e := SnapshotOpPrice(g.DB, p, cap, "synthesize", "weighted_character")
	if e != nil || mode == ChargeDisabled {
		socketFailure(client, "operation_price_unconfigured")
		return
	}
	if e = rewriteCanonicalTTSParams(&ev, state); e != nil {
		socketFailure(client, "invalid_task_configuration")
		return
	}
	data, _ = json.Marshal(ev)
	g.session(c, p, cap, client, data, &state, nil, sessionPlan{
		channel: channel, price: price, voice: state.Voice, bindVoice: true, op: "synthesize",
	})
}
func (g *Gateway) Realtime(c *gin.Context) {
	p, ok := g.preflight(c)
	if !ok {
		return
	}
	defer g.release(p.User.Id)
	name := c.Query("model")
	if name == "" {
		name = "qwen3-asr-flash-realtime"
	}
	cap, e := loadCapability(g.DB, name, "cn-beijing", "/api-ws/v1/realtime")
	if e != nil || cap.Protocol != "asr_realtime" || !p.Allows(name, cap.Model) {
		failure(c, 403, "model_not_allowed_or_not_verified")
		return
	}
	client, e := upgrade(c)
	if e != nil {
		return
	}
	defer client.Close()
	channel, e := SelectChannel(g.DB, p, cap)
	if e != nil {
		socketFailure(client, "channel_unavailable")
		return
	}
	price, e := SnapshotPrice(g.DB, p, cap)
	if e != nil {
		socketFailure(client, "price_unavailable")
		return
	}
	g.session(c, p, cap, client, nil, nil, &ASRState{}, sessionPlan{channel: channel, price: price})
}

type sessionPlan struct {
	channel   model.Channel
	price     Price
	voice     string
	bindVoice bool
	op        string
}

func (g *Gateway) session(c *gin.Context, p Principal, cap Capability, client *websocket.Conn, initial []byte, native *NativeState, asr *ASRState, plan sessionPlan) {
	channel := plan.channel
	price := plan.price
	if channel.Id == 0 {
		socketFailure(client, "channel_unavailable")
		return
	}
	endpoint, e := UpstreamURL(*channel.BaseURL, cap.Path, cap.Model)
	if e != nil {
		socketFailure(client, "upstream_configuration_error")
		return
	}
	hardware, e := g.prepareHardwareAudio(c, p, cap, price)
	if e != nil {
		socketFailure(client, e.Error())
		return
	}
	dispatched := false
	id := uuid.NewString()
	if hardware != nil {
		id = hardware.bill.ID
	}
	snapshot, _ := json.Marshal(price)
	bill := &model.BailianBill{ID: id, Scope: hash([]byte(id)), PayloadHash: hash(append([]byte(cap.Model), initial...)), UserID: p.User.Id, TokenID: p.Token.Id, ChannelID: channel.Id, Model: cap.Model, Group: p.User.Group, PriceSnapshot: string(snapshot)}
	amount, e := price.Quota(1, 1)
	if e != nil {
		socketFailure(client, "price_unavailable")
		return
	}
	if amount <= 0 {
		socketFailure(client, "reservation_failed")
		return
	}
	dbctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	if hardware == nil {
		_, e = model.ReserveBailian(g.DB.WithContext(dbctx), bill, amount)
	}
	cancel()
	if e != nil {
		socketFailure(client, "reservation_failed")
		return
	}
	known := int64(0)
	review := false
	reason := "not_submitted"
	defer func() {
		ctx, done := context.WithTimeout(context.Background(), 5*time.Second)
		defer done()
		if hardware != nil {
			if err := hardware.finish(native, asr, dispatched); err != nil {
				log.Printf("hardware audio settlement pending bill=%s error_type=%T", id, err)
			}
			return
		}
		if err := model.FinishBailian(g.DB.WithContext(ctx), id, known, review, 0, reason); err != nil {
			log.Printf("bailian settlement pending bill=%s", id)
		}
	}()
	// A dial only creates a session; no content is submitted before its durable marker.
	dialer := websocket.Dialer{HandshakeTimeout: 10 * time.Second}
	up, resp, e := dialer.DialContext(g.Context, endpoint, http.Header{"Authorization": {"Bearer " + channel.Key}, "OpenAI-Beta": {"realtime=v1"}})
	if e != nil {
		if resp != nil && resp.Body != nil {
			resp.Body.Close()
		}
		socketFailure(client, "upstream_handshake_failed")
		return
	}
	defer up.Close()
	dbctx, cancel = context.WithTimeout(context.Background(), 5*time.Second)
	if hardware == nil {
		e = model.SubmitBailian(g.DB.WithContext(dbctx), id)
	}
	cancel()
	if e != nil {
		review = true
		reason = "submission_marker_uncertain"
		socketFailure(client, "ledger_unavailable")
		return
	}
	dispatched = true
	review = true
	reason = "connection_interrupted"
	if initial != nil {
		if e = socketWrite(up, 1, initial); e != nil {
			socketFailure(client, "upstream_write_failed")
			return
		}
	}
	_ = client.SetReadDeadline(time.Now().Add(6 * time.Minute))
	_ = up.SetReadDeadline(time.Now().Add(6 * time.Minute))
	up.SetReadLimit(MaxFrame)
	ctx, stop := context.WithCancel(g.Context)
	defer stop()
	events := make(chan wsFrame, 8)
	var readers sync.WaitGroup
	readers.Add(2)
	go func() { defer readers.Done(); readSocket(ctx, client, false, events) }()
	go func() { defer readers.Done(); readSocket(ctx, up, true, events) }()
	defer func() { stop(); client.Close(); up.Close(); readers.Wait() }()
	started := time.Now()
	lastClient := started
	finishAt := time.Time{}
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	recheck := func() error {
		check, done := context.WithTimeout(context.Background(), 3*time.Second)
		defer done()
		db := g.DB.WithContext(check)
		fresh, e := Authenticate(db, c.Request, p.IP)
		if e != nil {
			return e
		}
		if fresh.User.Id != p.User.Id || fresh.User.Group != p.User.Group || fresh.Token.Id != p.Token.Id || fresh.Token.UnlimitedQuota != p.Token.UnlimitedQuota || !fresh.Allows(cap.Model, cap.Model) {
			return errors.New("account_changed")
		}
		var ch model.Channel
		if e = db.First(&ch, channel.Id).Error; e != nil {
			return e
		}
		if ch.Status != model.ChannelStatusEnabled || ch.Key != channel.Key || ch.BaseURL == nil || *ch.BaseURL != *channel.BaseURL || !listHas(ch.Models, cap.Model) || !listHas(ch.Group, p.User.Group) {
			return errors.New("channel_changed")
		}
		current, e := loadCapability(db, cap.Model, cap.Region, cap.Path)
		if e != nil {
			return e
		}
		if current.Protocol != cap.Protocol {
			return errors.New("capability_changed")
		}
		if plan.bindVoice {
			bound, e := g.authorizePrivateOrCatalog(p, cap, plan.voice)
			if e != nil || bound.Id != channel.Id {
				return errors.New("voice_channel_revoked")
			}
		}
		return nil
	}
	for {
		select {
		case <-ctx.Done():
			reason = "gateway_shutdown"
			return
		case now := <-ticker.C:
			if now.Sub(started) > 5*time.Minute || now.Sub(lastClient) > 60*time.Second || !finishAt.IsZero() && now.Sub(finishAt) > 20*time.Second {
				reason = "session_timeout"
				socketFailure(client, reason)
				return
			}
			if recheck() != nil {
				reason = "authorization_revoked"
				socketFailure(client, reason)
				return
			}
		case frame := <-events:
			if frame.err != nil {
				return
			}
			if frame.upstream {
				var typ string
				if native != nil {
					if frame.kind == 2 {
						if cap.Protocol != "tts_inference" || !native.Ready {
							reason = "invalid_upstream_binary"
							return
						}
					} else {
						typ, e = native.Server(frame.data)
						if e != nil {
							reason = "upstream_protocol_error"
							socketFailure(client, reason)
							return
						}
					}
					if native.UsageSeen {
						target, err := price.Quota(native.ConfirmedUnits, 1)
						if err != nil {
							reason = "invalid_usage"
							return
						}
						if target > known {
							check, done := context.WithTimeout(context.Background(), 5*time.Second)
							if hardware == nil {
								err = model.ConfirmBailian(g.DB.WithContext(check), id, target)
							}
							done()
							if err != nil {
								reason = "usage_exceeds_hold_or_ledger_error"
								socketFailure(client, "usage_reconciliation_required")
								return
							}
							known = target
						}
					}
				} else {
					if frame.kind != 1 {
						reason = "invalid_upstream_binary"
						return
					}
					typ, e = asr.Server(frame.data)
					if e != nil {
						reason = "upstream_protocol_error"
						socketFailure(client, reason)
						return
					}
				}
				if typ == "task-finished" || typ == "session.finished" {
					if native != nil {
						review = native.Units > 0 && !native.UsageSeen
					} else {
						if asr.UsageSeen {
							known, e = price.Quota(asr.ConfirmedSeconds, 1)
						} else {
							known, e = price.Quota(asr.Bytes, int64(asr.Rate*2))
						}
						// Realtime ASR has a validated local meter: admitted PCM duration.
						// It is authoritative for this registered capability even when the
						// provider omits a usage object.
						review = e != nil
					}
					reason = "completed"
					if review {
						reason = "completed_without_usage"
					}
					// Deliver the final event even if the client then disconnects.
					_ = socketWrite(client, frame.kind, frame.data)
					return
				}
				// Defense in depth: never forward a credential echoed by an upstream.
				if frame.kind == 1 && strings.Contains(string(frame.data), channel.Key) {
					reason = "upstream_secret_echo"
					socketFailure(client, "upstream_protocol_error")
					return
				}
				if e = socketWrite(client, frame.kind, frame.data); e != nil {
					return
				}
				continue
			}
			lastClient = time.Now()
			if recheck() != nil {
				reason = "authorization_revoked"
				socketFailure(client, reason)
				return
			}
			var ceiling int64
			if native != nil {
				e = native.Client(frame.kind, frame.data)
				if e == nil {
					ceiling, e = native.Ceiling(price)
				}
			} else {
				if frame.kind != 1 {
					e = errors.New("text_required")
				} else {
					e = asr.Client(frame.data)
				}
				if e == nil && asr.Rate > 0 {
					ceiling, e = price.Quota(asr.Bytes, int64(asr.Rate*2))
				}
			}
			if e != nil {
				reason = "invalid_client_event"
				socketFailure(client, reason)
				return
			}
			seconds := 0.0
			if native != nil && native.Protocol == "asr_inference" {
				seconds = float64(native.Units) / float64(native.SampleRate*2)
			} else if asr != nil && asr.Rate > 0 {
				seconds = float64(asr.Bytes) / float64(asr.Rate*2)
			}
			if seconds > time.Since(started).Seconds()*2+2 {
				reason = "audio_rate_limit"
				socketFailure(client, reason)
				return
			}
			check, done := context.WithTimeout(context.Background(), 5*time.Second)
			if hardware == nil {
				e = model.EnsureBailianHold(g.DB.WithContext(check), id, ceiling)
			} else if native != nil {
				e = hardware.grow(native.Units, 1)
			} else if asr.Rate > 0 {
				e = hardware.grow(asr.Bytes, int64(asr.Rate*2))
			}
			done()
			if e != nil {
				reason = "quota_or_ledger_rejected"
				socketFailure(client, reason)
				return
			}
			if e = socketWrite(up, frame.kind, frame.data); e != nil {
				reason = "upstream_write_uncertain"
				return
			}
			if (native != nil && native.Finishing || asr != nil && asr.Finishing) && finishAt.IsZero() {
				finishAt = time.Now()
			}
		}
	}
}

type wsFrame struct {
	kind     int
	data     []byte
	err      error
	upstream bool
}

func readSocket(ctx context.Context, ws *websocket.Conn, upstream bool, events chan<- wsFrame) {
	for {
		kind, data, e := ws.ReadMessage()
		select {
		case events <- wsFrame{kind, data, e, upstream}:
		case <-ctx.Done():
			return
		}
		if e != nil {
			return
		}
	}
}
