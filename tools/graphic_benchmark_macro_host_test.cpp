// Compiles the production helper.h macros. Must not redefine BENCHMARK.
#include <cassert>

#include "helper.h"

int main() {
    int n = 0;
    BENCHMARK(n++)
    BENCHMARK(n++)
    BENCHMARK_CLASS_RESET
    BENCHMARK_CLASS_REPORT
    assert(n == 2);
    return 0;
}
