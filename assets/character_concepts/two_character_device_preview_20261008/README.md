# 两组人物设备效果预览

2026-10-08，内置image_gen照片合成。不是已烧录图片或精确像素排版；生成结果可略偏离提示框，不能用预览测性能。

建议首版：第一组适配160×240框并保持比例，实际人物宽度可能约145像素；第二组约200×220。偏性能候选第一组140×220框，第二组180×198；未实机测试，不能承诺8 FPS。

## 第一组提示词

Use case: compositing. Image 1 is the DEVICE PHOTO EDIT TARGET with a woman already inside the screen. Image 2 is the EXACT selected dark-haired pink-trim blouse character to substitute. Preserve all device shell, camera, red knobs, base, desk, wires and laptop outside LCD unchanged. Preserve same light gray-lilac geometric wallpaper inside LCD. Replace woman with the complete visible silhouette from Image 2, including its waist and cropped sleeve ends, without inventing hands or legs or extra skirt.
Important layout: logical screen 320x320, target placement box x=80..240,y=80..320 (160x240); preserve source aspect ratio, so actual character width may be about145 logical pixels, do not stretch to fill160. Hair top around y=300 and lowest cropped waist/sleeves flush with screen bottom y=795 on this1448x1086photo. This is75% inner LCD height, top25% empty wallpaper. Visible figure physical width about310 image pixels, centered near x=750, NOT full LCD width. Display exact hairstyle, face, violet eyes, earring and clothing. Match source framing, show all side hair, fixed photo perspective. No text, labels, interface, watermark. Output one complete realistic device mockup.

## 第二组提示词

Use case compositing. Image1 is real device photo edit target, image2 exact blue-haired cheek-resting character with two complete hands. Replace ONLY woman inside LCD with image2, preserve entire device photo and same lilac geometric wallpaper. The logical screen320x320. Set character target natural width200height220 logical pixels, centered and bottom aligned; about62.5%LCDwidth and68.75%LCDheight. Physical LCD approx x410..1095,y130..795: exact character silhouette should fit x=538..967 and y=338..795. Do not enlarge face to fill screen. Include full blue hair, face, cheek-supporting hand and entire lower hand fingers and white-blue sleeves. No table, props, text or UI. Keep identical character pose, clothing and anatomy; hair top near y338, fingers/sleeves bottom near795, ample empty upper wallpaper. No distortion. Output entire photorealistic device photo, not a screen-only crop.

