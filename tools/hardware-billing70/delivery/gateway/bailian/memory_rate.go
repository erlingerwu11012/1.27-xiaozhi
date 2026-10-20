package bailian

import "time"

// Account-level Alibaba limits; one native gateway owns all product traffic.
// A rejected local request has no upstream call or charge.
func (g *Gateway) memoryRateAllow(path string, now time.Time) bool {
	g.memoryRateMu.Lock()
	defer g.memoryRateMu.Unlock()
	minute := now.Unix() / 60
	if minute != g.memoryRateMinute {
		g.memoryRateMinute = minute
		g.memoryRateTotal = 0
		g.memoryRateAdd = 0
		g.memoryRateSearch = 0
	}
	add := path == "add" || path == "add-async"
	search := path == "memory_nodes/search"
	if g.memoryRateTotal >= 3000 || (add && g.memoryRateAdd >= 120) || (search && g.memoryRateSearch >= 300) {
		return false
	}
	g.memoryRateTotal++
	if add {
		g.memoryRateAdd++
	}
	if search {
		g.memoryRateSearch++
	}
	return true
}
