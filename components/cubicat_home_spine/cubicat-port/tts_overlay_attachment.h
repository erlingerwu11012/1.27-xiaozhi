#pragma once
#include <spine/spine.h>

namespace cubicat {
// Run before any tracks start. Standalone animations may rely on a setup
// attachment that an idle track underneath would otherwise override.
inline bool PrepareTtsOverlayAttachment(spine::Skeleton& skeleton,
                                        const char* animation_name,
                                        const char* slot_name) {
    auto* slot = skeleton.findSlot(slot_name);
    auto* data = skeleton.getData();
    auto* animation = data->findAnimation(animation_name);
    if (!slot || !animation) return false;
    const auto& attachment = slot->getData().getAttachmentName();
    const int slot_index = slot->getData().getIndex();
    if (attachment.isEmpty() || !skeleton.getAttachment(slot_index, attachment)) return false;
    auto& timelines = animation->getTimelines();
    for (size_t i = 0; i < timelines.size(); ++i) {
        auto* timeline = timelines[i];
        if (timeline->getRTTI().isExactly(spine::AttachmentTimeline::rtti) &&
            static_cast<spine::AttachmentTimeline*>(timeline)->getSlotIndex() == slot_index) {
            return true; // Preserve explicitly authored attachment changes.
        }
    }
    auto* key = new spine::AttachmentTimeline(1, slot_index);
    key->setFrame(0, 0.0f, attachment);
    spine::Vector<spine::Timeline*> overlay_timelines(timelines);
    overlay_timelines.add(key);
    // Reconstruct to refresh Animation's private property-ID lookup too.
    auto* overlay = new spine::Animation(animation->getName(), overlay_timelines,
                                         animation->getDuration());
    auto& animations = data->getAnimations();
    for (size_t i = 0; i < animations.size(); ++i) {
        if (animations[i] == animation) {
            timelines.clear(); // Transfer ownership to the replacement.
            animations[i] = overlay;
            delete animation;
            return true;
        }
    }
    assert(false); // findAnimation and getAnimations share storage.
    return false;
}
} // namespace cubicat
