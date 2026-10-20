package bailian

import (
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/songquanpeng/one-api/common/blacklist"
	"github.com/songquanpeng/one-api/common/network"
	"github.com/songquanpeng/one-api/model"
	"gorm.io/gorm"
)

type Principal struct {
	User  model.User
	Token model.Token
	Key   string
	IP    string
}

func Authenticate(db *gorm.DB, r *http.Request, ip string) (Principal, error) {
	p := Principal{IP: ip}
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(auth, "Bearer sk-") {
		return p, errors.New("one_api_token_required")
	}
	p.Key = strings.TrimPrefix(auth, "Bearer sk-")
	if len(p.Key) < 16 || len(p.Key) > 48 || strings.ContainsAny(p.Key, " \r\n\t-") {
		return p, errors.New("invalid_token")
	}
	if e := db.Where("`key` = ?", p.Key).Take(&p.Token).Error; e != nil {
		return p, errors.New("invalid_token")
	}
	if e := db.First(&p.User, p.Token.UserId).Error; e != nil {
		return p, errors.New("invalid_user")
	}
	if os.Getenv("HW_BILLING_ENABLED") == "1" && p.Token.Status == model.TokenStatusExhausted {
		hardware, e := model.HasHardwareWallet(db, p.User.Id)
		if e != nil {
			return p, errors.New("billing_state_unavailable")
		}
		if hardware {
			p.Token.Status = model.TokenStatusEnabled
		}
	}
	if p.Token.Status != model.TokenStatusEnabled || (p.Token.ExpiredTime != -1 && p.Token.ExpiredTime <= time.Now().Unix()) || p.User.Status != model.UserStatusEnabled || blacklist.IsUserBanned(p.User.Id) {
		return p, errors.New("account_or_token_disabled")
	}
	if p.Token.Subnet != nil && *p.Token.Subnet != "" && !network.IsIpInSubnets(r.Context(), ip, *p.Token.Subnet) {
		return p, errors.New("ip_not_allowed")
	}
	return p, nil
}

func (p Principal) Allows(requested, canonical string) bool {
	return p.Token.Models == nil || *p.Token.Models == "" || (listHas(*p.Token.Models, requested) && listHas(*p.Token.Models, canonical))
}

func SelectChannel(db *gorm.DB, p Principal, cap Capability) (model.Channel, error) {
	var channels []model.Channel
	if e := db.Where("type = ? AND status = ?", 17, model.ChannelStatusEnabled).Order("priority DESC, id ASC").Find(&channels).Error; e != nil {
		return model.Channel{}, e
	}
	for _, ch := range channels {
		if !listHas(ch.Group, p.User.Group) || !listHas(ch.Models, cap.Model) || ch.BaseURL == nil {
			continue
		}
		if _, e := UpstreamURL(*ch.BaseURL, cap.Path, cap.Model); e != nil {
			continue
		}
		if ch.ModelMapping != nil && strings.TrimSpace(*ch.ModelMapping) != "" && strings.TrimSpace(*ch.ModelMapping) != "{}" {
			continue
		}
		return ch, nil
	}
	return model.Channel{}, errors.New("no_authorized_channel")
}

func SnapshotPrice(db *gorm.DB, p Principal, cap Capability) (Price, error) {
	var price Price
	if json.Unmarshal([]byte(cap.PriceJSON), &price) != nil {
		return price, errors.New("invalid_price")
	}
	var opt model.Option
	e := db.Where("`key` = ?", "GroupRatio").Take(&opt).Error
	if e == nil {
		var groups map[string]json.Number
		dec := json.NewDecoder(strings.NewReader(opt.Value))
		dec.UseNumber()
		if dec.Decode(&groups) != nil {
			return price, errors.New("invalid_group_ratio")
		}
		ratio, ok := groups[p.User.Group]
		if !ok {
			return price, errors.New("missing_group_ratio")
		}
		price.GroupMultiplier = ratio.String()
	} else if !errors.Is(e, gorm.ErrRecordNotFound) {
		return price, e
	}
	if price.Region != cap.Region {
		return price, errors.New("price_region_mismatch")
	}
	_, e = price.Quota(1, 1)
	return price, e
}
