#pragma once
#include <string>
#include <cJSON.h>
void InitializeHomeRenderConfig();
bool SaveHomeRenderMode(const std::string &name, std::string &error);
bool SaveHomeRenderOptions(const std::string &profile, int spi_mhz, bool pixel_diff, std::string &error);
cJSON *HomeRenderStatusJson();
