/**
 * Host-side runner for production arbiter + pending submit policy unit tests.
 */

#include <cstdio>

#include "main_ws_open_arbiter.h"
#include "main_ws_submit_policy.h"

int main() {
    if (!main_ws_open::RunUnitTests()) {
        std::fprintf(stderr, "main_ws_open::RunUnitTests FAILED\n");
        return 1;
    }
    if (!main_ws_submit::RunUnitTests()) {
        std::fprintf(stderr, "main_ws_submit::RunUnitTests FAILED\n");
        return 1;
    }
    std::printf("ALL HOST TESTS PASSED\n");
    return 0;
}
