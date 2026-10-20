# 设备配色半身角色原图

日期：2026-10-05。

输出：device_assistant_half_body.png，使用内置image_gen生成，并进行一次背景去除与半身构图编辑。角色配色参考用户设备照片的白色、红色与深灰；正面半身、短发、简洁科技服装。

这是合成透明PNG设计原图，不是分层PSD、Spine工程或动作资源。制作Spine时需要拆分头发、脸、眼睛、嘴、身体和手臂，补齐被遮挡部位；按原生320×320预览决定显示尺寸，保持长宽比例。

## 初始生成提示词

Use case: stylized-concept.
Asset type: a high resolution original 2D character illustration to be used as the visual master reference for a future Spine 4.2 half-body rig on an ESP32-S3 device with a 320x320 screen.
Primary request: Design ONE original adult female anime virtual assistant, frontal waist-up standing portrait. Her appearance should harmonize with a physical desktop device whose casing is matte white with small vivid red angular accents, a black screen bezel, and a dark graphite angular base. Produce the character artwork itself, not the device, not a photo mockup, and not a character sheet.
Subject and style: clearly adult young woman, friendly and poised, appealing professional Japanese anime game illustration, precise clean line art, polished restrained cel shading, clear expressive warm reddish amber eyes, small gentle closed-mouth smile. Dark graphite shoulder-length bob haircut built from a few broad readable hair locks, simple bangs that leave both eyes visible, one small red geometric hair accessory. A compact non-bulky white futuristic assistant uniform jacket, vivid red shoulder panels and a few broad red seam accents, dark charcoal high collar undershirt, gray structural details and short sleeves, tasteful fully covered chest, no text, no branding, no weapons or hand-held objects. The futuristic uniform has a simple angular visual language matching the device's white/red/graphite shell, without excessive armor or tiny mechanical details.
Composition: strictly front facing, eye level, head and torso centered, head, both shoulders, both arms and entire waist clearly visible. Arms relaxed beside torso, subtly spaced so elbow and forearm silhouettes can be separated later; both hands naturally resting near the sides of the waist and fully visible. Neutral symmetrical rig-friendly pose, no crossed arms, no extreme perspective, no foreground occlusion. Moderately large head and legible face for a small display, anatomically coherent adult proportions. Hair contained within shoulder width, no long loose ribbons, no wide outstretched arms, no extra decorations outside the silhouette. Full hair top with modest safety margin, clean horizontal lower crop at waist, a compact portrait silhouette suitable to scale proportionally into approximately 180x240 display pixels. High resolution portrait composition, ideally 1024x1536 or similar, with character using most of the canvas and minimal empty margins. Maintain crisp face and clothing details when reduced.
Scene/backdrop: genuine transparent alpha background, no scenery, no floor, no cast shadow, no gradient, no checkerboard drawn into pixels.
Constraints: one character only; original design; no letters, labels, numbers, watermark, device frame, multiple views, duplicated limbs or disconnected parts. This is a finished flat illustration intended for later manual separation into layered Spine parts; do not simulate a PSD, do not draw bones or meshes. Preserve broad distinct color masses with strong outline readability and limit complex semitransparent effects.

## 最终编辑提示词

Edit the provided generated character illustration into a usable transparent waist-up Spine art reference. Preserve this exact original adult anime woman's identity, face, warm red eyes, graphite bob, red geometric hair clip, white/red/charcoal futuristic uniform, frontal view, clean linework and polished cel shading.
Two precise changes:
1. Remove ALL background and colored light haze completely. Every pixel outside the person must be truly transparent alpha=0, including between arms and torso and hair edge gaps. Do not keep any dark background, red glow, beige halo, shadow, floor, checkerboard illustration or colored backdrop. Solid interior skin/hair/clothes must be opaque, with only narrow antialiased edges.
2. Reframe as a compact head-to-waist half-body portrait for a 320x320 screen. Include complete top of hair with a small breathing margin, both shoulders, torso and jacket down to the waist. Cut the lower image horizontally just below the jacket waist hem, do not include thighs. Let the relaxed arms continue naturally down and be cropped at the same bottom line; no need to include hands that are below the waist. Keep both elbow silhouettes within the image width; do not stretch the body. Make the face prominent and keep a roughly 3:4 portrait subject bounding box, suitable to display approximately 180x240 pixels. Retain original excellent face and costume details. One character only, no device or labels. Export as high-resolution transparent PNG cutout.

