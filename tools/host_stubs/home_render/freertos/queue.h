#pragma once
#include "FreeRTOS.h"
struct HostQueue;
using QueueHandle_t = HostQueue *;
QueueHandle_t xQueueCreate(UBaseType_t capacity, UBaseType_t item_size);
BaseType_t xQueueReceive(QueueHandle_t, void *item, TickType_t);
BaseType_t xQueueSend(QueueHandle_t, const void *item, TickType_t);
void vQueueDelete(QueueHandle_t);
