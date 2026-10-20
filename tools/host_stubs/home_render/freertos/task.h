#pragma once
#include "FreeRTOS.h"
struct HostTask;
using TaskHandle_t = HostTask *;
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void *), const char *, uint32_t, void *, UBaseType_t,
                                   TaskHandle_t *, BaseType_t);
void vTaskDelete(TaskHandle_t);
void xTaskNotifyGive(TaskHandle_t);
uint32_t ulTaskNotifyTake(BaseType_t, TickType_t);
UBaseType_t uxTaskGetStackHighWaterMark(TaskHandle_t);
void vTaskDelay(TickType_t);
void taskYIELD();
