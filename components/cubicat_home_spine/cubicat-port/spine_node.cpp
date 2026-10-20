#include "spine_node.h"
#include "tts_overlay_attachment.h"
#include "spine/AtlasAttachmentLoader.h"
#include "spine/Atlas.h"
#include "spine/SkeletonBinary.h"
#include "spine/SkeletonClipping.h"
#include "spine/AnimationStateData.h"
#include "spine/SkeletonData.h"
#include "spine/ClippingAttachment.h"
#include "spine/RegionAttachment.h"
#include "spine/MeshAttachment.h"
#include "spine/SlotData.h"
#include "spine/Bone.h"
#include "utils/logger.h"
#include "utils/helper.h"
#include "spine/Animation.h"
#include "spine/Physics.h"
#include "graphic_engine/drawable/polygon2d.h"
#include "graphic_engine/renderer/renderer.h"
#include "utils/home_perf.h"
#include "utils/home_render_options.h"

using namespace cubicat;

float* g_pVertexPositionsCache = nullptr;
uint32_t g_iVertexPositionsCacheSize = 0;
float* getVertexPositionsCache(uint32_t vertexCount) {
    if (vertexCount > g_iVertexPositionsCacheSize) {
        if (g_pVertexPositionsCache) free(g_pVertexPositionsCache);
        g_pVertexPositionsCache = (float*)psram_prefered_malloc(vertexCount * 2 * sizeof(float));
        assert(g_pVertexPositionsCache);
        g_iVertexPositionsCacheSize = vertexCount;
    }
    return g_pVertexPositionsCache;
}

bool slotIsOutRange(Slot &slot, int startSlotIndex, int endSlotIndex) {
    const int index = slot.getData().getIndex();
    return startSlotIndex > index || endSlotIndex < index;
}

bool nothingToDraw(Slot &slot, int startSlotIndex, int endSlotIndex) {
    Attachment *attachment = slot.getAttachment();
    if (!attachment ||
        slotIsOutRange(slot, startSlotIndex, endSlotIndex) ||
        !slot.getBone().isActive())
        return true;
    const auto &attachmentRTTI = attachment->getRTTI();
    if (attachmentRTTI.isExactly(ClippingAttachment::rtti))
        return false;
    if (slot.getColor().a == 0)
        return true;
    if (attachmentRTTI.isExactly(RegionAttachment::rtti)) {
        if (static_cast<RegionAttachment *>(attachment)->getColor().a == 0)
            return true;
    } else if (attachmentRTTI.isExactly(MeshAttachment::rtti)) {
        if (static_cast<MeshAttachment *>(attachment)->getColor().a == 0)
            return true;
    }
    return false;
}
#define ASSIGN_TEXTURE(attachmentType, attachment) \
    auto att = (attachmentType*)attachment; \
    auto atlasRegion = (AtlasRegion*)att->getRegion(); \
    if (atlasRegion) { \
        auto page = atlasRegion->page; \
        if (page->texturePath.length() > 0 && \
            (!HomeV2Drawing() || poly->materialPtr()->texturePtr().get() != page->texture)) { \
            auto it = m_textureMap.find(page->texturePath.buffer()); \
            if (it == m_textureMap.end()) { \
                TexturePtr texture = SharedPtr<Texture>((Texture*)page->texture); \
                if (texture) { \
                    m_textureMap[page->texturePath.buffer()] = texture; \
                } \
            } \
            poly->getMaterial()->setTexture(m_textureMap[page->texturePath.buffer()]); \
        } \
    }

CubicatTextureLoader SpineNode::m_sTextureLoader;

SpineNode::SpineNode() {
}

SpineNode::~SpineNode() {
    unload();
}

SpineNode* SpineNode::createSpine() {
    return NEW SpineNode();
}

bool SpineNode::loadWithBinaryFile(const std::string &skeletonBinaryFile, const std::string &atlasFile, float scale) {
    unload();
    LOGI("Home Spine loading atlas=%s skeleton=%s scale=%.3f", atlasFile.c_str(), skeletonBinaryFile.c_str(), scale);
    m_pAtlas = new Atlas(atlasFile.c_str(), &m_sTextureLoader, true);
    if (m_pAtlas == nullptr || m_pAtlas->getPages().size() == 0 || m_pAtlas->getRegions().size() == 0) {
        LOGE("Home Spine atlas load failed: pages=%u regions=%u", m_pAtlas == nullptr ? 0 : (unsigned)m_pAtlas->getPages().size(),
             m_pAtlas == nullptr ? 0 : (unsigned)m_pAtlas->getRegions().size());
        return false;
    }
    LOGI("Home Spine atlas ready: pages=%u regions=%u", (unsigned)m_pAtlas->getPages().size(),
         (unsigned)m_pAtlas->getRegions().size());
    m_pAttachmentLoader = new AtlasAttachmentLoader(m_pAtlas);

    SkeletonBinary binary(m_pAttachmentLoader);
    binary.setScale(scale);
    SkeletonData *skeletonData = binary.readSkeletonDataFile(skeletonBinaryFile.c_str());
    if (!skeletonData || !binary.getError().isEmpty()) {
        LOGE("Spine: Error reading skeleton data: %s", binary.getError().buffer());
        return false;
    }
    m_pSkeleton = new Skeleton(skeletonData);
    initialize();
    LOGI("Home Spine skeleton ready: animations=%u skins=%u", (unsigned)m_vAnimationNames.size(),
         (unsigned)m_pSkeleton->getData()->getSkins().size());
    return true;
}
void SpineNode::unload() {
    m_slotMinWorldY.clear();
    clearDrawables();
    m_textureMap.clear();
    if (m_pSkeleton) {
        delete m_pSkeleton->getData();
        delete m_pSkeleton;
        m_pSkeleton = nullptr;
    }
    if (m_pAnimState) {
        delete m_pAnimState->getData();
        delete m_pAnimState;
        m_pAnimState = nullptr;
    }
    if (m_pClipper) {
        delete m_pClipper;
        m_pClipper = nullptr;
    }
    if (m_pAttachmentLoader) {
        delete m_pAttachmentLoader;
        m_pAttachmentLoader = nullptr;
    }
    if (m_pAtlas) {
        delete m_pAtlas;
        m_pAtlas = nullptr;
    }
}
void SpineNode::initialize() {
    m_pClipper = new SkeletonClipping();
    m_pAnimState = new AnimationState(new AnimationStateData(m_pSkeleton->getData()));
    auto& anims = m_pSkeleton->getData()->getAnimations();
    for (int i=0;i<anims.size();i++) {
        m_vAnimationNames.push_back(anims[i]->getName().buffer());
    }
    setSkinByIndex(0);
}
void SpineNode::setSkinByName(const std::string &skinName) {
    if (m_pSkeleton) {
        if (!skinName.empty())
            m_pSkeleton->setSkin(skinName.c_str());
    }
}

void SpineNode::setSkinByIndex(int idx) {
    if (m_pSkeleton) {
        auto data = m_pSkeleton->getData();
        auto skins = data->getSkins();
        // remove default skin
        skins.removeAt(0);
        if (!skins.size())
            return;
        idx = idx % skins.size();
        if (idx < 0)
            idx = skins.size() + idx;
        m_pSkeleton->setSkin(skins[idx]);
    }
}

TrackEntry* SpineNode::setAnimation(int trackIndex, int animIndex, bool loop) {
    auto name = getAnimationName(animIndex);
    return setAnimation(trackIndex, name, loop);
}
TrackEntry* SpineNode::setAnimation(int trackIndex, const std::string &name, bool loop) {
    if (!m_pSkeleton || !m_pAnimState)
        return nullptr;
    Animation *animation = m_pSkeleton->getData()->findAnimation(name.c_str());
    if (!animation) {
        LOGE("Spine: Animation not found: %s", name.c_str());
        return nullptr;
    }
    return m_pAnimState->setAnimation(trackIndex, animation, loop);
}
TrackEntry* SpineNode::addAnimation(int trackIndex, int animIndex, bool loop, float delay) {
    auto name = getAnimationName(animIndex);
    return addAnimation(trackIndex, name, loop, delay);
}
TrackEntry* SpineNode::addAnimation(int trackIndex, const std::string &name, bool loop, float delay) {
    if (!m_pSkeleton || !m_pAnimState)
        return nullptr;
    Animation *animation = m_pSkeleton->getData()->findAnimation(name.c_str());
    if (!animation) {
        LOGI("Spine: Animation not found: %s", name.c_str());
        return nullptr;
    }
    return m_pAnimState->addAnimation(trackIndex, animation, loop, delay);
}
void SpineNode::clearTrack(int trackIndex) {
    if (m_pAnimState) {
        m_pAnimState->setEmptyAnimation(trackIndex, 0);
    }
}

bool SpineNode::prepareTtsOverlayAttachment(const char* animation, const char* slot) {
    return m_pSkeleton && PrepareTtsOverlayAttachment(*m_pSkeleton, animation, slot);
}

void SpineNode::update(float deltaTime, bool parentDirty) {
    Node::update(deltaTime, parentDirty);
    if (!isVisible())
     return;

    if (m_pSkeleton && m_pAnimState) {
        {
            HomePerfScope timing(HomePerf().animation);
            m_pAnimState->update(deltaTime);
            m_pAnimState->apply(*m_pSkeleton);
            m_pSkeleton->update(deltaTime);
            m_pSkeleton->updateWorldTransform(Physics_Update);
        }
        HomePerfScope timing(HomePerf().mesh);
        updateMesh();
    }
}
void SpineNode::updateMesh() {
    auto& drawables = getDrawables();
    auto& drawOrders = m_pSkeleton->getDrawOrder();
    int slotCount = drawOrders.size();
    if (slotCount > drawables.size()) {
        int count = slotCount - drawables.size();
        for (int i=0; i<count; ++i) {
            auto poly = Polygon2D::create(Mesh2D::create(nullptr, 0, nullptr, 0, true));
            poly->getMaterial()->setBilinearFilter(m_bUseBilinearFilter);
            attachDrawable(poly);
        }
    }
    for (int i=0; i<slotCount; ++i) {
        Slot *slot = drawOrders[i];
        Attachment* attachment = slot->getAttachment();
        auto poly = drawables[i]->cast<Polygon2D>();
        const auto clip = m_slotMinWorldY.find(slot->getData().getIndex());
        if (clip != m_slotMinWorldY.end()) poly->setMinWorldY(clip->second);
        else poly->clearMinWorldY();
        auto mesh = poly->getMesh();
        if (nothingToDraw(*slot, 0, slotCount)) {
            poly->setVisible(false);
            m_pClipper->clipEnd(*slot);
            continue;
        } else {
            poly->markDirty();
            poly->setVisible(true);
            if (slot->getData().getBlendMode() == BlendMode_Additive) {
                poly->getMaterial()->setBlendMode(cubicat::BlendMode::Additive);
            } else if (slot->getData().getBlendMode() == BlendMode_Multiply) {
                poly->getMaterial()->setBlendMode(cubicat::BlendMode::Multiply);
            } else if (slot->getData().getBlendMode() == BlendMode_Normal) {
                poly->getMaterial()->setBlendMode(cubicat::BlendMode::Normal);
            } else {
                // Screen and any unknown blend mode are unsupported by the Home renderer.
                LOGE("Spine: unsupported blend mode %d on slot %s; hiding slot",
                     static_cast<int>(slot->getData().getBlendMode()),
                     slot->getData().getName().buffer());
                poly->setVisible(false);
                m_pClipper->clipEnd(*slot);
                continue;
            }
        }
        if (attachment->getRTTI().isExactly(RegionAttachment::rtti)) {
            auto region = (RegionAttachment *)slot->getAttachment();
            if (region->getRegion() == nullptr) {
                // Sequence frame not resolved yet; hide until SequenceTimeline applies.
                poly->setVisible(false);
                m_pClipper->clipEnd(*slot);
                continue;
            }
            ASSIGN_TEXTURE(RegionAttachment, attachment)
            auto& uvs = region->getUVs();
            // update 4 vertices position and uv
            float vertices[8];
            region->computeWorldVertices(*slot, vertices, 0, 2);
            mesh->updateVertices(vertices, 4);
            static uint16_t indices[] = {0, 1, 2, 0, 2, 3};
            if (HomeV2Drawing()) {
                mesh->updateIndicesIfChanged(indices, 6);
                mesh->updateUVsIfChanged(uvs.buffer(), uvs.size());
            } else {
                mesh->updateIndices(indices, 6);
                mesh->updateUVs(uvs.buffer(), uvs.size());
            }
        } else if (attachment->getRTTI().isExactly(MeshAttachment::rtti)) {
            auto meshAttachment = static_cast<MeshAttachment *>(attachment);
            if (meshAttachment->getRegion() == nullptr) {
                // Sequence frame not resolved yet; hide until SequenceTimeline applies.
                poly->setVisible(false);
                m_pClipper->clipEnd(*slot);
                continue;
            }
            ASSIGN_TEXTURE(MeshAttachment, attachment)
            auto mesh = poly->getMesh();
            // convert vertices position to world space 
            int vCount = meshAttachment->getWorldVerticesLength() >> 1;
            float* vertPos = getVertexPositionsCache(vCount);
            meshAttachment->computeWorldVertices(*slot, vertPos);
            mesh->updateVertices(vertPos, vCount);
            if (HomeV2Drawing()) {
                mesh->updateIndicesIfChanged(meshAttachment->getTriangles().buffer(), meshAttachment->getTriangles().size());
                mesh->updateUVsIfChanged(meshAttachment->getUVs().buffer(), meshAttachment->getUVs().size());
            } else {
                mesh->updateIndices(meshAttachment->getTriangles().buffer(), meshAttachment->getTriangles().size());
                mesh->updateUVs(meshAttachment->getUVs().buffer(), meshAttachment->getUVs().size());
            }
        } else if (attachment->getRTTI().isExactly(ClippingAttachment::rtti)) {
            // Clipping is unsupported by the Home renderer; reject rather than clip.
            LOGE("Spine: ClippingAttachment unsupported at slot %d; hiding slot", i);
            poly->setVisible(false);
            m_pClipper->clipEnd(*slot);
            continue;
        } else {
            // printf("Unhandled attachment type : %s\n", attachment->getRTTI().getClassName());
            m_pClipper->clipEnd(*slot);
            continue;
        }
    }
}
bool SpineNode::setSlotMinWorldY(const std::string& slotName, int minY) {
    if (!m_pSkeleton) return false;
    auto* slot = m_pSkeleton->findSlot(slotName.c_str());
    if (!slot) return false;
    m_slotMinWorldY[slot->getData().getIndex()] = minY;
    return true;
}

void SpineNode::setScale(const Vector2f& scale) {
    if (m_pSkeleton) {
        m_pSkeleton->setScaleX(scale.x);
        m_pSkeleton->setScaleY(scale.y);
    }
}
void SpineNode::setPosition(const Vector2f& pos) {
    Node2D::setPosition(pos);
}
const std::vector<std::string>& SpineNode::getAnimationNames() {
    return m_vAnimationNames;
}
std::string SpineNode::getAnimationName(int idx) {
    if (m_vAnimationNames.empty())
        return "";
    idx = idx % m_vAnimationNames.size();
    if (idx < 0) idx = m_vAnimationNames.size() + idx;
    return m_vAnimationNames[idx];
}
void SpineNode::useBilinearFilter(bool b) {
    m_bUseBilinearFilter = b;
    auto& drawables = getDrawables();
    for (auto& d : drawables) {
        d->getMaterial()->setBilinearFilter(b);
    }
}
