#pragma once

#include "task.h"

#ifndef MALLOC_CAP_INTERNAL
#define MALLOC_CAP_INTERNAL (1u << 0)
#endif
#ifndef MALLOC_CAP_8BIT
#define MALLOC_CAP_8BIT (1u << 1)
#endif

BaseType_t xTaskCreateWithCaps(TaskFunction_t fn, const char* name,
                               uint32_t stack_bytes, void* arg,
                               UBaseType_t priority, TaskHandle_t* handle,
                               UBaseType_t caps);
