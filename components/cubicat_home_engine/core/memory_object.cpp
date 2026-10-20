#include "memory_object.h"
#include "memory_allocator.h"
#include <cstdlib>

void *MemoryObject::operator new(size_t size) { return psram_prefered_malloc(size); }
void *MemoryObject::operator new[](size_t size) { return psram_prefered_malloc(size); }
void *MemoryObject::operator new(size_t size, const char *, int) { return psram_prefered_malloc(size); }
void *MemoryObject::operator new[](size_t size, const char *, int) { return psram_prefered_malloc(size); }
void MemoryObject::operator delete(void *ptr) { free(ptr); }
void MemoryObject::operator delete[](void *ptr) { free(ptr); }
