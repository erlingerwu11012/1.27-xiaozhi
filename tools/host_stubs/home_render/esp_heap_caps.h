#pragma once
#include <cstddef>
constexpr unsigned MALLOC_CAP_INTERNAL = 1, MALLOC_CAP_SPIRAM = 2, MALLOC_CAP_DMA = 4,
                   MALLOC_CAP_8BIT = 8;
void *heap_caps_malloc(size_t, unsigned);
void heap_caps_free(void *);
size_t heap_caps_get_free_size(unsigned);
