#include "spine_extension.h"
#include "esp_heap_caps.h"
#include <string.h>
#include "spine/SpineString.h"
#include "core/memory_allocator.h"

extern "C" char* cubicat_home_read_asset(const char* name, int* length);

CubicatSpineExtension* g_Instance = nullptr;

CubicatSpineExtension::CubicatSpineExtension() {
}
void CubicatSpineExtension::init() {
    if (!g_Instance) {
        g_Instance = new CubicatSpineExtension();
        SpineExtension::setInstance(g_Instance);
    }
}
void* CubicatSpineExtension::_alloc(size_t size, const char *file, int line) {
    return psram_prefered_malloc(size);
}

void* CubicatSpineExtension::_calloc(size_t size, const char *file, int line) {
    void* ptr = _alloc(size, file, line); 
    if (ptr) {
        memset(ptr, 0, size);
        return ptr;
    }
    return  nullptr;
}

void* CubicatSpineExtension::_realloc(void *ptr, size_t size, const char *file, int line) {
    return psram_prefered_realloc(ptr, size);
}

void CubicatSpineExtension::_free(void *mem, const char *file, int line) {
    heap_caps_free(mem);
}

char* CubicatSpineExtension::_readFile(const String &path, int *length) {
    return cubicat_home_read_asset(path.buffer(), length);
}
