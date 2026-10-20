#include "texture_loader.h"
#include "utils/logger.h"

GetImageDataInMemory CubicatTextureLoader::m_pGetImageInMemory = nullptr;
ResLocation CubicatTextureLoader::m_eResLocation = MEMORY;

void CubicatTextureLoader::init(ResLocation location, GetImageDataInMemory getImageInMemory) {
    m_pGetImageInMemory = getImageInMemory;
    m_eResLocation = location;
}

void CubicatTextureLoader::load(AtlasPage& page, const String& path) {
    if (m_eResLocation != MEMORY || m_pGetImageInMemory == nullptr) {
        LOGE("Home Spine expects memory assets: %s", path.buffer());
        return;
    }

    const auto& image = m_pGetImageInMemory(path.buffer());
    page.texture = const_cast<void*>(image.data);
    // SpineNode uses texturePath as the key when it binds an atlas page to a mesh.
    page.texturePath = path;
    page.width = image.width;
    page.height = image.height;
    LOGI("Home Spine texture bound: %s (%dx%d, %p)", path.buffer(), image.width, image.height, image.data);
}

void CubicatTextureLoader::unload(void* texture) {
    (void)texture;
}

void CubicatTextureLoader::loadPNG(AtlasPage& page, const char* path) {
    (void)page;
    LOGE("File texture loading is disabled for Home Spine: %s", path);
}
