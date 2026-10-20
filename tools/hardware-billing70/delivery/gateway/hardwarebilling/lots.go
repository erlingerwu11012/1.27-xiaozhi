package hardwarebilling

import (
	"errors"
	"math/big"
)

// Lots must be loaded under an account-row lock, legacy first then paid FIFO.
type Lot struct {
	ID          string `json:"id"`
	Kind        string `json:"kind"`
	Remaining   Exact  `json:"remaining_points"`
	CNYPerPoint Exact  `json:"cny_per_point"`
}
type Allocation struct {
	LotID   string `json:"lot_id"`
	Kind    string `json:"kind"`
	Points  Exact  `json:"points"`
	SaleCNY Exact  `json:"sale_cny"`
}

// Allocate is pure: insufficiency leaves all supplied lots untouched. Legacy's
// old debit and the new CNY charge are supplied separately by verified pricing.
// A legacy lot covers its consumed fraction of the call; the remaining fraction
// is priced against new lots using cost/0.30, never old quota conversion.
func Allocate(lots []Lot, sale Exact, legacyDebit Exact) ([]Allocation, error) {
	remainingSale, e := Parse(string(sale))
	if e != nil {
		return nil, e
	}
	oldTotal, e := Parse(string(legacyDebit))
	if e != nil {
		return nil, e
	}
	fraction := big.NewRat(1, 1)
	var out []Allocation
	paidSeen := false
	seen := map[string]bool{}
	for _, lot := range lots {
		if lot.ID == "" || seen[lot.ID] {
			return nil, errors.New("invalid_lot_order")
		}
		seen[lot.ID] = true
		available, e := Parse(string(lot.Remaining))
		if e != nil {
			return nil, e
		}
		if lot.Kind == "legacy" {
			if paidSeen {
				return nil, errors.New("legacy_must_precede_paid")
			}
			if oldTotal.Sign() == 0 || available.Sign() == 0 {
				continue
			}
			need := new(big.Rat).Mul(oldTotal, fraction)
			take := new(big.Rat).Set(need)
			if take.Cmp(available) > 0 {
				take.Set(available)
			}
			covered := new(big.Rat).Quo(take, oldTotal)
			fraction.Sub(fraction, covered)
			// Legacy cash value is intentionally unknown, not inferred from 100 points/yuan.
			out = append(out, Allocation{lot.ID, lot.Kind, exact(take), "0"})
			continue
		}
		if lot.Kind != "paid" {
			return nil, errors.New("invalid_lot_kind")
		}
		if !paidSeen {
			remainingSale.Mul(remainingSale, fraction)
			paidSeen = true
		}
		rate, e := Parse(string(lot.CNYPerPoint))
		if e != nil || rate.Sign() == 0 {
			return nil, errors.New("invalid_lot_rate")
		}
		if remainingSale.Sign() == 0 {
			continue
		}
		capacity := new(big.Rat).Mul(available, rate)
		take := new(big.Rat).Set(remainingSale)
		if take.Cmp(capacity) > 0 {
			take.Set(capacity)
		}
		points := new(big.Rat).Quo(take, rate)
		out = append(out, Allocation{lot.ID, lot.Kind, exact(points), exact(take)})
		remainingSale.Sub(remainingSale, take)
	}
	if !paidSeen {
		remainingSale.Mul(remainingSale, fraction)
	}
	if remainingSale.Sign() > 0 {
		return nil, errors.New("insufficient_balance")
	}
	return out, nil
}
