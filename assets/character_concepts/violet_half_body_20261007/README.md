# 紫色挑染半身人物设计

日期：2026-10-07
生成方式：内置 image_gen，参考图衍生及照片编辑。

- character_original.png：人物原图，PNG；仍需人工分层、补全遮挡部位及绑定，不能直接作为 Spine 模型。
- device_mockup.png：设备照片合成预览，不是真机烧录结果。人物居中贴底，视觉高度约为屏幕的四分之三；壁纸使用浅灰紫、白色几何切面及红色点缀。
- 高分辨率设计稿不等于设备贴图尺寸；最终显示、贴图打包和性能需要另行处理。

## 原图生成提示词

Create a polished high-resolution anime character illustration derived from the supplied reference. Preserve the recognizable visual design: deep indigo shoulder-length hair with delicate rose-pink streaks, loose soft bangs, violet gradient eyes, small blue triangular earring, gentle blush and a warm subtle smile. Clearly an adult young woman. White everyday blouse with rose-pink collar and button placket, a small blue inner neckline, modest and fully clothed. No armor or futuristic uniform. Gentle head tilt and slight three-quarter torso, eyes toward viewer. Show the entire head, both shoulders, arms naturally resting near the sides and the torso down to upper hips; no hands or hair accidentally cropped at the sides. Compact waist-up silhouette, expressive readable face and clean hair groups appropriate as the design source for a future Spine puppet. Beautiful crisp anime linework, controlled soft cel shading, refined but uncluttered clothing details. Preserve the reference's appealing character style without reproducing its screenshot frame or overlay. One character only, isolated on a genuinely transparent background, no colored backdrop, no halo, no studio gradient, no floor, no cast shadow, no text, no subtitles, no UI, no logo, no watermark. Leave a little transparent margin above and at sides. This is the original character artwork, not a device mockup.

## 设备效果图提示词

Edit the supplied real device photograph by inserting a carefully designed screen composition ONLY inside its inner LCD. The other reference is the exact character artwork to use; keep that woman's face, head tilt, hair, white/pink blouse and dark skirt design consistent. Preserve the real device shell, red side knobs, camera, black bezel, angular graphite base, desk, wires and laptop as photographed. Do not change the device shape or surrounding photo.
Inside the near-square LCD, show the character as a waist-up companion, horizontally centered and anchored at the bottom. Character height must be approximately 75 percent of the actual inner LCD height, leaving the TOP QUARTER as unobstructed wallpaper. The photo is 1448x1086: LCD corners approximately (417,142),(1091,149),(1072,783),(417,777). Hair top should be near y=300, and the waist/upper-hip crop should meet the bottom inner display near y=780. Character width about 50 to 60 percent of inner display width. Do not enlarge the character to fill the whole display, and never crop her head or hair. Preserve aspect ratio. Arms and lower waist may end cleanly at the screen bottom. Use the actual supplied character, no substitute.
Design an elegant wallpaper that coordinates with BOTH the white/red/graphite physical device and the character's violet/pink palette: a very light warm-gray/lilac center, sparse white and graphite beveled geometric planes only near peripheral corners, a small muted rose-red slanted accent near an upper corner, subtle soft lighting, ample negative space around face. No bedroom, no sci-fi cockpit, no busy tech grid, no text, no icons or UI. Keep the character's face visibly separate from background; no halo. Wallpaper covers the entire inner LCD behind the character. Realistic perspective and restrained display luminosity, crisp screen artwork. Output one complete photorealistic device mockup photograph.

## 布局修正提示词

Make one precise layout correction to this device mockup. Keep the entire device photograph and current wallpaper unchanged. Uniformly scale the woman to 80 percent of her CURRENT size, anchored at her bottom waist crop and horizontally centered. Her hair currently starts near y=184 and her bottom meets y=794; the corrected hair top should be near y=305 while her bottom STILL meets y=794. Keep the exact face, proportions, hair and outfit, do not redraw a larger face or extend the torso to compensate. Result: woman takes about three quarters of the inner LCD's height, top quarter of LCD shows empty wallpaper; woman is about half of LCD width. Fill the newly exposed screen space with the same existing soft lilac geometric wallpaper. No other changes. Output the complete device photo.

