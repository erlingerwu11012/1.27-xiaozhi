# 贴底四分之三高度人物与配套壁纸

日期：2026-10-05。使用内置image_gen生成与编辑。

本次把四分之三解释为人物高度约占屏幕75%，不是人物面积占75%。参考320×320逻辑屏幕，人物约160×240，水平居中，下沿贴底，上方约留80像素。合成照片只用于构图参考，并非像素精确实机布局或已烧录画面。

文件：
- character_original.png：沿用上一版日常服饰人物原图，含脸、手、短裙和上半大腿。
- wallpaper_room_master.png：配套高分辨率方形房间壁纸，无人物；设备版本可在后续资源制作时导出320×320。
- device_screen_mockup_three_quarters.png：最新贴底、缩小人物与壁纸的设备合成预览。

## 壁纸生成提示词

Use case: illustration-story.
Asset type: standalone square wallpaper for a 320x320 desktop companion screen, high-resolution master approximately1024x1024.
Primary request: one clean original anime-style 2D background illustration of a cozy modern room that will sit BEHIND a centered adult anime virtual assistant in a white cardigan, red shirt and charcoal skirt. The foreground character will fill the central lower three-quarters of the screen height, so composition must leave the central lower area visually quiet and unobstructed.
Scene: softly lit calm contemporary studio room with muted blue-gray walls. On the far left a simple tall window and translucent curtain with broad soft morning-light color shapes; near the lower-left edge a short light wood desk with one closed red book. On the far right an understated narrow shelf or cabinet with a small green plant and two simple books. Pale warm wood or neutral floor along the lower strip. No people, no animals, no human silhouettes. Elegant relaxed everyday mood, not futuristic, no cyberpunk or control panels. White, light warm gray, muted dusty blue-gray and light wood as the palette, with only a small red accessory to harmonize with the device. The central wall is midtone desaturated blue-gray so a white cardigan and dark hair will contrast clearly.
Style: polished Japanese anime background illustration, clean coherent perspective, simplified broad readable color masses and restrained soft cel shading appropriate for viewing at320x320, no fine repeating grids or tiny details. The left and right furnishings stay mostly at the outer edges. Upper quarter can show pleasant light and a little room detail; central space from about x=25% to75% and y=25% to100% is reserved for the character, with no foreground furniture or plants covering that central area. No text, logos, numbers, watermarks, frame, device or character. One square wallpaper only, no variations, no side-by-side composition.

## 设备合成提示词

Edit Image 1 ONLY within its inner LCD screen to make an accurate proposed device-screen layout.
Reference roles:
Image 1: edit target, user's real photographed white/red desktop device with black bezel and dark graphite base, wires and laptop. Preserve everything outside the LCD exactly, including camera viewpoint and desk. Do not change screen or case geometry.
Image 2: foreground character insert, use the SAME original adult anime woman with graphite bob, red eyes and hairclip, soft white cardigan, plain red top, charcoal short skirt, relaxed arms and visible upper thighs. Keep her exact face, costume, pose and proportions. Extract only the character, remove all her existing studio gray/beige glow backdrop.
Image 3: wallpaper insert, use this exact square illustration of the blue-gray room wall, tall left window, soft curtain, wood floor, small red book on left desk and plant/shelf on right. Fit the wallpaper to the LCD and preserve its broad composition.
Critical foreground layout: The user explicitly requests the character be SMALLER and LOWER. The source head-to-upper-thigh figure must occupy exactly about75 percent of the LCD height, not90 or100 percent. The head top is approximately one-quarter of screen height down from the top. The source lower-thigh crop aligns exactly with the LCD bottom edge. Horizontally center her, retain all of her head, both hands, skirt and the visible upper-thigh portion. In logical320x320 coordinates, the character bounds are approximately x=80..240 and y=80..320 (160x240). These numbers describe composition only; DO NOT draw coordinates or labels. Leave a full top quarter showing wallpaper with no character. Maintain the portrait's aspect ratio without stretching, do not enlarge the head independently, do not make her fill the whole display, do not crop at waist. The wall and other wallpaper features should remain visible around her. No furniture in front of the character.
Map the wallpaper-and-character composition to the exact perspective of the existing inner LCD rectangle, entirely inside the black bezel. The screen illustration remains 2D anime artwork with a subtle believable LCD appearance; preserve all outside-screen photographic content. No captions, text, UI or extra subjects. Deliver ONE landscape device photograph, not a collage. This is a visual mockup, not proof of actual firmware display.

## 人物大小位置修正提示词

Precise size and position correction to the foreground anime woman ONLY in the LCD of this provided device mockup. Preserve the real device, desk, laptop, wires, screen bounds, and the existing room wallpaper exactly.
The woman in the current mockup is still TOO LARGE: her hair starts near image y=232 and the LCD starts near y=142, leaving only14% top space. Fix this.
Shrink the entire existing woman uniformly to about85% of her current size. Keep her lower thigh cut at the LCD bottom near image y=790. Her complete hair top should therefore move DOWN to near y=305, which is about25% down inside the LCD. Do NOT keep her hair at y=232. The target subject height is about485 image pixels inside a roughly650-pixel-high LCD, i.e. THREE QUARTERS of the LCD height. In320x320 screen coordinates the full source character crop is about160x240, horizontally centered, with head top at y=80 and bottom at y=320. Do not print these numbers.
Preserve exactly her adult face, bob, hairclip, cardigan, red shirt, skirt, neutral arms, hands and visible thighs; scale her as a complete portrait without changing anatomy or independently enlarging the head. Keep the bottom aligned, not vertically centered; full top quarter must be wallpaper with no character. Reconstruct previously occluded wallpaper from the same blue-gray wall and wood floor as necessary. Both hands remain inside LCD, slightly above or at its bottom edge. The updated woman must visibly be smaller than in the reference, with more background visible above and to the sides. No added labels, no text, no UI, no extra characters. Only LCD foreground figure size/location changes.

