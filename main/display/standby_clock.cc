#include "standby_clock.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

namespace {
struct Point { int x, y; };
struct Shape { const Point* points; int count; };
constexpr Point zero[] = {{6,0},{34,0},{40,6},{40,58},{34,64},{6,64},{0,58},{0,6}};
constexpr Point one[] = {{14,0},{28,0},{28,54},{38,54},{38,64},{2,64},{2,54},{16,54},{16,12},{2,12},{2,8}};
constexpr Point two[] = {{0,0},{34,0},{40,6},{40,32},{10,44},{10,54},{40,54},{40,64},{0,64},{0,38},{30,26},{30,10},{0,10}};
constexpr Point three[] = {{0,0},{34,0},{40,6},{40,58},{34,64},{0,64},{0,54},{30,54},{30,37},{8,37},{8,27},{30,27},{30,10},{0,10}};
constexpr Point four[] = {{0,0},{10,0},{10,27},{30,27},{30,0},{40,0},{40,64},{30,64},{30,37},{0,37}};
constexpr Point five[] = {{0,0},{40,0},{40,10},{10,10},{10,27},{34,27},{40,33},{40,58},{34,64},{0,64},{0,54},{30,54},{30,37},{0,37}};
constexpr Point six[] = {{6,0},{40,0},{40,10},{10,10},{10,27},{34,27},{40,33},{40,58},{34,64},{6,64},{0,58},{0,6}};
constexpr Point seven[] = {{0,0},{40,0},{40,15},{20,64},{8,64},{28,10},{0,10}};
constexpr Point nine[] = {{6,0},{34,0},{40,6},{40,58},{34,64},{0,64},{0,54},{30,54},{30,37},{6,37},{0,31},{0,6}};
constexpr Shape shapes[] = {{zero,8},{one,11},{two,13},{three,14},{four,10},
                            {five,14},{six,12},{seven,7},{zero,8},{nine,12}};

// Coordinates are doubled so pixel-center tests use integers, including
// corner cuts. No software double-precision work on the ESP32-S3.
bool Inside(const Shape& shape, int x, int y) {
    bool inside = false;
    for (int i = 0, j = shape.count - 1; i < shape.count; j = i++) {
        const auto a = shape.points[i], b = shape.points[j];
        const int ax = 2*a.x, ay = 2*a.y, bx = 2*b.x, by = 2*b.y;
        if ((ay > y) != (by > y)) {
            const int cross = (bx-ax)*(y-ay) - (x-ax)*(by-ay);
            if ((by > ay && cross > 0) || (by < ay && cross < 0)) inside = !inside;
        }
    }
    return inside;
}

bool DigitPixel(int digit, int x, int y) {
    if (!Inside(shapes[digit], x, y)) return false;
    if (x >= 20 && x < 60) {
        if (digit == 0 && y >= 20 && y < 108) return false;
        if ((digit == 8 || digit == 9) && y >= 20 && y < 54) return false;
        if ((digit == 6 || digit == 8) && y >= 74 && y < 108) return false;
    }
    return true;
}

void Text(uint16_t* pixels, int width, int height, const char* text,
          int top, int digit_width, int digit_height, int gap) {
    int total = 0;
    for (const char* c = text; *c; ++c) {
        total += (*c == ':' || *c == '.') ? std::max(2, digit_width / 4) : digit_width;
        if (c[1]) total += gap;
    }
    int left = (width - total) / 2;
    for (const char* c = text; *c; ++c) {
        const int w = (*c == ':' || *c == '.') ? std::max(2, digit_width / 4) : digit_width;
        for (int y = 0; y < digit_height; ++y) {
            for (int x = 0; x < w; ++x) {
                const int nx = (2*x + 1) * 40 / w;
                const int ny = (2*y + 1) * 64 / digit_height;
                bool on = false;
                if (*c >= '0' && *c <= '9') on = DigitPixel(*c - '0', nx, ny);
                else if (*c == ':') on = (ny >= 32 && ny < 50) || (ny >= 82 && ny < 100);
                else if (*c == '.') on = y >= digit_height - w;
                else if (*c == '-') on = ny >= 54 && ny < 74;
                const int px = left + x, py = top + y;
                if (on && px >= 0 && px < width && py >= 0 && py < height)
                    pixels[py * width + px] = 0xFFFF;
            }
        }
        left += w + gap;
    }
}
}  // namespace

bool StandbyClockText::operator==(const StandbyClockText& other) const {
    return valid == other.valid && std::strcmp(time, other.time) == 0 &&
           std::strcmp(date, other.date) == 0;
}

StandbyClockText MakeStandbyClockText(time_t now) {
    StandbyClockText out;
    if (now <= 1000000000L) return out;
    struct tm local = {};
#ifdef _WIN32
    if (localtime_s(&local, &now) != 0) return out;
#else
    if (!localtime_r(&now, &local)) return out;
#endif
    if (local.tm_year < 100 || local.tm_year > 8099) return out;
    std::strftime(out.time, sizeof(out.time), "%H:%M", &local);
    std::strftime(out.date, sizeof(out.date), "%Y.%m.%d", &local);
    out.valid = true;
    return out;
}

void DrawStandbyClock(uint16_t* pixels, int width, int height,
                      const StandbyClockText& text) {
    if (!pixels || width <= 0 || height <= 0) return;
    std::fill_n(pixels, static_cast<size_t>(width) * height, uint16_t{0});
    Text(pixels, width, height, text.time, height * 122 / 320,
         std::max(1, width * 40 / 320), std::max(1, height * 64 / 320),
         std::max(1, width * 7 / 320));
    if (text.valid)
        Text(pixels, width, height, text.date, height * 216 / 320,
             std::max(1, width * 10 / 320), std::max(1, height * 16 / 320),
             std::max(1, width * 3 / 320));
}
