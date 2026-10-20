#pragma once
#include <atomic>
#include <string>
extern std::atomic<bool> HostFailPsram, HostFailHeap;
extern std::string HostFailTask;
extern std::atomic<unsigned> HostNotifyDelay;
extern std::atomic<size_t> HostInternalFree;
void HostJoinTasks();
