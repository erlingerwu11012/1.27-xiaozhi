// Package hardwarebilling is scoped to Xiaozhi hardware. It must not be used by
// the independent Aimi wallet or infer billing from a context-window estimate.
package hardwarebilling

import (
	"errors"
	"math/big"
)

// Exact serializes a reduced fraction. Rounding is permitted only for display.
type Exact string

func Parse(v string) (*big.Rat, error) {
	if len(v) == 0 || len(v) > 512 {
		return nil, errors.New("invalid_exact_amount")
	}
	r, ok := new(big.Rat).SetString(v)
	if !ok || r.Sign() < 0 {
		return nil, errors.New("invalid_exact_amount")
	}
	return r, nil
}

func exact(r *big.Rat) Exact   { return Exact(r.RatString()) }
func zero() *big.Rat           { return new(big.Rat) }
func integer(v int64) *big.Rat { return new(big.Rat).SetInt64(v) }
func SaleCNY(cost Exact) (Exact, error) {
	c, e := Parse(string(cost))
	if e != nil {
		return "", e
	}
	return exact(c.Mul(c, big.NewRat(10, 3))), nil
}

// CashRate belongs to one paid recharge lot, not to a globally averaged package.
func CashRate(paidCents, grantedPoints int64) (Exact, error) {
	if paidCents <= 0 || grantedPoints <= 0 {
		return "", errors.New("invalid_paid_lot")
	}
	return exact(new(big.Rat).Quo(new(big.Rat).SetFrac(big.NewInt(paidCents), big.NewInt(100)), integer(grantedPoints))), nil
}

func Display(v Exact, digits int) (string, error) {
	if digits < 0 || digits > 18 {
		return "", errors.New("invalid_display_precision")
	}
	r, e := Parse(string(v))
	if e != nil {
		return "", e
	}
	return r.FloatString(digits), nil
}
