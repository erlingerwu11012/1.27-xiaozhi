# 设备整体搭配：白红灰日常服饰＋斜切几何背景

日期：2026-10-05。使用内置image_gen生成／编辑。

## 设计依据

- 以用户现有白色壳体、黑色屏幕边框、红色斜切标记和深灰底座作为视觉基准。
- 人物使用白色短外套、红色上衣和深灰短裙，保留自然面孔与短发；减少原针织开衫的按钮及细碎装饰。服装为日常休闲风。
- 背景从机身提取斜切边、几何块和小面积红色点缀；中央为较安静的中浅灰面，以便深色头发、白色衣服和脸部轮廓分离。
- 保留人物头到上半大腿构图。设备合成预览按人物高度约占屏幕75%、水平居中、下沿贴底设计；上方约留四分之一背景。
- 不将简单配色等同于设备帧率保证；本次只做美术和构图预览，没有修改固件或生成Spine动画。

## 文件

- character_original.png：1024×1536设计原图，仍有柔光背景。不是分层PSD，后续Spine制作需要去背景、拆层和补齐遮挡部分。
- wallpaper_geometric_master.png：独立方形高清壁纸，无人物。后续设备资源制作时再导出320×320。
- device_product_mockup.png：基于用户设备照片的合成预览，非实机运行照片，不是像素精确布局或性能验收。

## 人物提示词

Use case: identity-preserve / stylized-concept.
Input image roles: Image1 is the character EDIT TARGET. Image2 is only a product design reference, the user's physical white/red/graphite desktop device. Do not draw the device or any photo scene into the character output.
Create a refined ORIGINAL 2D anime adult companion character art that belongs to this product family, rather than a random person on unrelated wallpaper.
Preserve exactly Image1's adult woman's recognizable face, warm red eyes, graphite bob, red geometric hair clip, calm friendly smile, and front-facing head-through-upper-thigh framing. Keep both hands and visible bare upper thighs, natural adult proportions, a neutral standing rig-friendly pose. Make eyes readable and hair from few broad locks.
Refine the everyday clothing into understated designer athleisure: a short white lightweight zip-front casual jacket worn open with clean flat fabric panels, no knit ribbing, no decorative buttons, relaxed simple sleeves pushed near elbow, a muted vivid red plain crew-neck top, and a high-waisted charcoal A-line short skirt with only three or four broad pleats. Add a VERY small red diagonal fabric accent at one jacket cuff and a subtle dark-gray side seam, echoing the device's slanted red markers and graphite structural edges. Clothing remains wearable soft fabric, not armor or a futuristic uniform. No metal shoulder pads, electronics, harness, tactical gear, sci-fi HUD, heavy accessories, logos or writing. The white jacket, red center and charcoal skirt form three clear color masses, minimal stitching, tasteful fully covered neckline.
Professional product-family rationale: the device has large quiet white surfaces, disciplined graphite borders and small slanted red accents. Make the outfit readable, restrained and intentional; retain a friendly approachable human feeling.
Composition: one centered portrait, complete head top with a little margin, shoulders and torso, both relaxed arms close to the body, complete hands beside hips, skirt and some bare upper thigh, cropped horizontally at mid thigh. No full legs or knees, no crossed arms. Clean polished anime illustration, restrained cel shading and precise line work. High resolution approximately1024x1536, visible figure fills most canvas. Use actual transparent alpha with no background, no studio gradient or halo, no lighting haze, no floor, no cast shadow or checkerboard drawn into image. Only the single foreground character, fully opaque interiors and narrow antialiasing at silhouette. This is a flat art reference for later manual Spine layering.

## 壁纸提示词

Use case: stylized-concept.
Asset type: high-resolution square screen wallpaper, approximately1024x1024, for a320x320 physical desktop companion device.
The reference photograph is a product design reference ONLY. Create a standalone wallpaper, NOT a device mockup. There must be no device, character, room, furniture, text or logos.
Professional product exterior design direction: translate the photographed product's large matte-white surfaces, black/graphite structure, restrained vivid red diagonal tabs and chamfered corners into a sophisticated restrained abstract graphic. The screen should look like part of the same coherent white-red-graphite product family. A friendly anime person wearing white/red/charcoal will sit centered in the lower75% of the wallpaper; design the background around that use.
Composition: a quiet medium-light neutral warm gray center covering most of the square, chosen to separate both dark hair and white clothing. At the extreme upper-left and left edges, two broad asymmetrical off-white and light-gray diagonally cut planar shapes, with a narrow graphite separator; at the upper-left a SINGLE small vivid red slanted parallelogram accent like the device's red tabs. At the far lower-right, a small graphite chamfered wedge and an understated thin red diagonal inset, clipped to the corner. Keep roughly x=25%..75%, y=25%..100% nearly uniform gray for the portrait, and leave the top quarter airy and quiet. This must be a well-composed designed background with controlled asymmetry and generous negative space, not a busy pattern.
Materials / visual treatment: matte solid surfaces, very subtle soft shadow along ONE paper-like plane edge to suggest depth, polished minimal industrial editorial design; broad clean shapes readable at320x320. White/light-gray/graphite about95% of the design, red no more than5%, no blue dominant hues. Subtle warm tone to soften the hard-shell product. No shiny chrome, sci-fi circuitry, glow, grids, HUD, stars, particles, tiny ornament, neon, heavily textured surface or shiny gradients. Avoid making a second rectangular bezel inside the screen; do not draw a complete frame. All accent geometry stays at margins so it does not run across the face or torso area. Square wallpaper edge to edge, one image only.

## 设备合成提示词

Professional product-family screen mockup. Edit Image1's inner LCD content ONLY.
Input roles:
Image1 is the exact real photograph to preserve: white angular desktop device with restrained red slanted tabs, red side knobs, black bezel, top camera and graphite base. Keep everything outside inner LCD unchanged, including desk mat, wires, laptop, enclosure geometry, perspective, lighting and focus.
Image2 is the exact adult anime companion foreground art to insert: graphite bob, warm red eyes and geometric hairclip, white short casual zip jacket, simple red shirt, charcoal A-line skirt, relaxed arms, hands and some bare upper thighs. Preserve her exact identity, face, clothing and proportions; remove any gray/beige studio backdrop or halo from this insert.
Image3 is the exact new abstract product-family wallpaper to insert: neutral gray center with asymmetric matte-white/graphite diagonally cut edge planes and restrained red parallelogram accents. Preserve its design, but keep all accents behind the figure. Do not invent a room or furniture.
CRITICAL layout: the full foreground source portrait from head top through upper-thigh crop is only75% of LCD height, horizontally centered and bottom aligned. There must be roughly25% empty wallpaper above her complete hair top. Logical320x320 screen target is approximately160x240 pixels, x80..240, y80..320. In the reference photograph the screen is around650pixels tall from y142 to790; woman's hair top should be abouty305 and lower visible-thigh crop aroundy790. Never place hair near top of screen or y230. Do not enlarge the foreground to fill display. Keep complete face, hair, jacket, skirt, both hands and exposed upper-thigh section. No full body, no knees, no source stretching or individually enlarged head. She occupies about one half the screen width. Clear background left, right and above.
Visual result should read as a designed integrated product: matching external casing palette and oblique motifs, quiet central background, warm approachable natural human character, controlled red accents. Character artwork remains2D anime displayed on a physical LCD with mild believable screen brightness, not realistic human skin.
Apply perspective mapping to exact LCD corners, entirely inside thick black bezel. Do not alter case or create another inner bezel. No text, UI widgets, captions, logos, labels, particle effects, lens flares or extra characters. One realistic device photograph with updated LCD only; not collage. This is a concept mockup, not an actual flashed device test.

## 构图修正提示词

Precise layout correction. Edit only the anime foreground woman inside the LCD of this device concept photograph. Preserve all device photography and the existing abstract white/gray/graphite/red wallpaper.
The current woman is too tall: top of her hair is about imagey196, while the LCD top isy142 and bottomy781, so she fills over90% of the display. The user's firm requirement is only75% of display height and LOWER.
Uniformly REDUCE the entire existing woman's width AND height to82% of her current size, anchored at the lower-thigh crop at LCD bottomy781. Move her with the shrink so her new hair top is aroundy300..305, NOTy196. She should be about480pixels tall inside a640pixel-high LCD. Keep her horizontally centered. Leave approximately the entire top quarter of the display as unobstructed gray wallpaper. In logical320x320 pixels, full source figure bounds aboutx80..240, y80..320.
Preserve her exact face, short dark bob, red hairclip, white casual jacket, red crewneck shirt, charcoal short skirt, both hands, visible upper thighs, pose and proportions. Do not enlarge head independently, do not crop at waist, do not extend legs. Let the bottom cut remain at lower visible upper thighs. Reconstruct wallpaper newly revealed behind the smaller figure. Do not alter wallpaper corner accents, real casing, bezel, camera, knobs, base, desk, wires or laptop. No new text, UI, labels or extra subjects. The result must show noticeably more blank gray area above her head and more wallpaper to either side than the input.

