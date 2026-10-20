// Inspect an asset package with the exact compatibility gate used by device OTA.
#include "spine_role_preflight.h"
#include <fstream>
#include <iostream>
#include <vector>
#include <stdexcept>

// The production preflight uses memory buffers exclusively.
extern "C" char* cubicat_home_read_asset(const char*, int* length) {
    if (length) *length = 0;
    return nullptr;
}

std::vector<char> ReadRoleFile(const char* path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot read role file");
    return {std::istreambuf_iterator<char>(input), {}};
}

int main(int argc, char** argv) {
    try {
        if (argc != 4) throw std::runtime_error("SKEL ATLAS SKIN required");
        auto skeleton = ReadRoleFile(argv[1]);
        auto atlas = ReadRoleFile(argv[2]);
        const auto result = spine_role_preflight::Check(
            skeleton.data(), skeleton.size(), atlas.data(), atlas.size(), argv[3]);
        std::cout << "result=" << spine_role_preflight::ErrorToString(result.code)
                  << " runtime=" << result.runtime_version << " detail=" << result.detail << "\n";
        return result.ok() ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << error.what() << "\n";
        return 1;
    }
}
