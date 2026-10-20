#ifndef CAMERA_H
#define CAMERA_H

#include "camera_image_buffer.h"
#include <string>
#include <vector>

class Camera {
public:
    virtual ~Camera() = default;
    virtual void SetExplainUrl(const std::string& url, const std::string& token) = 0;
    virtual bool Capture() = 0;
    virtual bool SetHMirror(bool enabled) = 0;
    virtual bool SetVFlip(bool enabled) = 0;
    virtual std::string Explain(const std::string& question) = 0;
    // Upload this exact captured frame.  Callers using a live preview must not
    // rely on an implementation's mutable "last frame" buffer.
    virtual std::string Explain(const std::string& question,
                                const CameraJpegBuffer& jpeg) = 0;
};

#endif // CAMERA_H
