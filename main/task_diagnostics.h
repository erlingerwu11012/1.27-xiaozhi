#ifndef TASK_DIAGNOSTICS_H
#define TASK_DIAGNOSTICS_H

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace task_diag {

void LogCurrentTask(const char* owner, const char* phase, int expected_priority, int expected_core);
void LogTaskHandle(const char* owner, const char* label, TaskHandle_t handle,
                   int expected_priority, int expected_core);
void LogNamedTasks(const char* owner, const char* reason);
void LogTaskList(const char* owner, const char* reason);
void LogMemoryStage(const char* owner, const char* phase);
void RunPsramBenchmark(const char* owner, const char* reason);
void StartPeriodicTaskLogger();

}  // namespace task_diag

#endif  // TASK_DIAGNOSTICS_H
