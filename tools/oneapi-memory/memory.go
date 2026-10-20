package bailian

// Native HTTP forwarding only. Identity decisions, schedules and memory rules
// belong to the device service; this adapter does not change them.
import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/songquanpeng/one-api/model"
)

const memoryPrefix = "/bailian/api/v2/apps/memory"
const memoryUpstream = "https://dashscope.aliyuncs.com/api/v2/apps/memory/"

func MemoryEnabled() bool {
	id, _ := strconv.Atoi(os.Getenv("BAILIAN_MEMORY_CHANNEL_ID"))
	return id > 0
}

func (g *Gateway) MemoryRoutes(r *gin.Engine) {
	if !MemoryEnabled() {
		return
	}
	for _, path := range []string{"add", "add-async", "memory_nodes/search", "profile_schemas"} {
		r.POST(memoryPrefix+"/"+path, g.memoryProxy)
	}
	for _, path := range []string{"memory_nodes", "memory_nodes/:id", "events/:id", "profile_schemas", "profile_schemas/:id", "profile_schemas/:id/user_profile"} {
		r.GET(memoryPrefix+"/"+path, g.memoryProxy)
	}
	r.PATCH(memoryPrefix+"/memory_nodes/:id", g.memoryProxy)
	r.DELETE(memoryPrefix+"/memory_nodes/:id", g.memoryProxy)
	r.PATCH(memoryPrefix+"/profile_schemas/:id", g.memoryProxy)
}

var memoryIDPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,128}$`)
var memoryClient = &http.Client{
	Timeout:       95 * time.Second,
	CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
}

func (g *Gateway) memoryProxy(c *gin.Context) {
	p, ok := g.httpAuth(c)
	if !ok {
		return
	}
	// One API also serves other ordinary accounts. Native memory APIs have
	// account-wide node/template access, so only the trusted backend uses them.
	// This is an existing administrator role check, not a device whitelist.
	if p.User.Role < model.RoleAdminUser {
		failure(c, http.StatusForbidden, "memory_backend_credential_required")
		return
	}
	if !g.acquire(p.User.Id) {
		failure(c, 429, "gateway_busy")
		return
	}
	defer g.release(p.User.Id)
	ctx, cancel := context.WithTimeout(c.Request.Context(), 90*time.Second)
	defer cancel()
	id, _ := strconv.Atoi(os.Getenv("BAILIAN_MEMORY_CHANNEL_ID"))
	var channel model.Channel
	if g.DB.WithContext(ctx).First(&channel, id).Error != nil || channel.Type != 17 || channel.Status != model.ChannelStatusEnabled || strings.TrimSpace(channel.Key) == "" {
		failure(c, 503, "memory_channel_unavailable")
		return
	}
	if !listHas(channel.Group, p.User.Group) {
		failure(c, 403, "channel_group_not_authorized")
		return
	}
	if objectID := c.Param("id"); objectID != "" && !memoryIDPattern.MatchString(objectID) {
		failure(c, 400, "invalid_memory_resource_id")
		return
	}
	query, err := url.ParseQuery(c.Request.URL.RawQuery)
	if err != nil {
		failure(c, 400, "invalid_query")
		return
	}
	for _, values := range query {
		if len(values) != 1 {
			failure(c, 400, "duplicate_query_field")
			return
		}
	}
	var payload []byte
	if c.Request.Method == http.MethodPost || c.Request.Method == http.MethodPatch {
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 1024*1024)
		payload, err = io.ReadAll(c.Request.Body)
		if err != nil {
			failure(c, 413, "memory_body_too_large")
			return
		}
	}
	// Only explicitly registered routes reach here; the host cannot be supplied
	// by callers or overwritten by a chat-compatible channel BaseURL.
	path := strings.TrimPrefix(c.Request.URL.Path, memoryPrefix+"/")
	u := memoryUpstream + path
	if len(query) > 0 {
		u += "?" + query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, c.Request.Method, u, bytes.NewReader(payload))
	if err != nil {
		failure(c, 400, "invalid_memory_request")
		return
	}
	req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(channel.Key))
	req.Header.Set("Content-Type", "application/json")
	resp, err := memoryClient.Do(req)
	if err != nil {
		failure(c, 502, "memory_upstream_unreachable_or_result_unknown")
		return
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 4*1024*1024+1))
	if err != nil || len(raw) > 4*1024*1024 {
		failure(c, 502, "memory_upstream_response_unavailable")
		return
	}
	if resp.StatusCode >= 300 && resp.StatusCode < 400 {
		failure(c, 502, "memory_upstream_redirect_rejected")
		return
	}
	c.Header("Cache-Control", "no-store")
	if requestID := resp.Header.Get("X-Request-ID"); requestID != "" {
		c.Header("X-Request-ID", requestID)
	}
	c.Data(resp.StatusCode, "application/json", raw)
}
