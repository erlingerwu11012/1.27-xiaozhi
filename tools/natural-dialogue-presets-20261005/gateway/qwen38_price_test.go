package hardwarebilling

import "testing"

func TestQwen38PricesAndPermissionBoundaries(t *testing.T) {
 for _, tc := range []struct { model, cost string }{
  {"qwen3.8-flash", "0.0051"}, {"qwen3.8-max", "0.072"},
 } {
  for _, op := range []string{"llm", "summary", "habit"} {
   p, e := BeijingPrice(tc.model, op, false)
   if e != nil { t.Fatal(e) }
   got, e := p.Cost(measured(10000, 1000, 8000))
   if e != nil { t.Fatal(e) }
   equal(t, got, tc.cost)
   if p.Operation != op || p.Model != tc.model { t.Fatal("route changed") }
   if _, e := p.Cost(measured(991809, 0, 0)); e == nil { t.Fatal("out-of-range input accepted") }
   if _, e := BeijingPrice(tc.model, "vision", false); e == nil { t.Fatal("text model used for vision") }
   if _, e := BeijingPrice(tc.model+"-unverified", "llm", false); e == nil { t.Fatal("unknown alias accepted") }
  }
 }
}
