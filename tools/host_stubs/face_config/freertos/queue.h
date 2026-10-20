#pragma once

#include "FreeRTOS.h"

struct HostQueue;
using QueueHandle_t = HostQueue*;

QueueHandle_t xQueueCreate(UBaseType_t length, UBaseType_t item_size);
BaseType_t xQueueSend(QueueHandle_t queue, const void* item, TickType_t ticks);
BaseType_t xQueueReceive(QueueHandle_t queue, void* item, TickType_t ticks);
void vQueueDelete(QueueHandle_t queue);
