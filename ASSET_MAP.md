# 素材索引与可信等级
所有链接均为包内相对路径。

## 产品与场景
- [明亮版主图](assets/product-images/main-square-bright.png)：用户认可产品及明亮背景；旧文字设计未获认可。可参考光线、背景和产品表现，必须重新排版，不要沿用旧字。
- [无字外观参考](assets/product-images/appearance-white-textless.png)：已有生成效果图，用于 CMF / 外观方向，不是实拍或尺寸依据。
- [原型正侧面](assets/product-images/prototype-front-side.jpg)、[背侧面](assets/product-images/prototype-side-back.jpg)、[亮屏实拍](assets/product-images/prototype-screen-on.jpg)：实物结构参考，红旋钮与当前目标配色不同。
- [原屏幕艺术图](assets/product-images/screen-artwork-original.png)：原画参考；制作屏幕画面优先渲染真实 Spine + room.png。
- 这些图不是全角度精修图库；没有已验收的透明背景产品图、新机位精修图或可直接发布的整套详情页。

## CAD / 屏幕
- [尺寸数据](assets/models/dimensions.json) / [LCD 手册](assets/specs/YX40018ACT-specification.pdf)。装配朝向及安装深度仍须结合样机复核。
- assets/models/step/：8 个原始 STEP 零件，单位 mm，共用装配坐标。
- [parts-data.json](assets/models/parts-data.json)：8 件离散三角网格，name / positions / normals / indices / bounds。位置法线为 Base64 小端 Float32，索引为小端 Uint32。可导入 Blender 或 Three.js，无需重新画硬件。
- [Blender 导入脚本](tools/import_product_blender.py)：从该网格创建基础模型与配色，**未作为最终摄影材质和灯光模板验收**。
- [已实测导入的基础 Blender 文件](assets/models/product-geometry.blend)：本地 Blender 4.5.14 已成功导入 8 件几何；没有最终摄影灯光和屏幕，不能直接当成广告成图。
- assets/spine/：nvhai.skel、nvhai.atlas、texture.png、room.png、本地 spine-webgl.js 与原许可。
- [full-screen.html](assets/spine/full-screen.html)：旧渲染参考，按时间调用 drawAt(t)；不是自动播放器或最终验收成图。
- [动画清单](reference/animation-inventory.json) / [源码布局摘录](reference/screen-layout-source.md)。
- [idle 原始运行时抽帧 t=0](assets/screen-previews/idle-t0.png)、[t=1](assets/screen-previews/idle-t1.png)：浏览器实测渲染，角色和原壁纸同屏。见 [运行检查](reference/screen-runtime-check.json)，不是新绘人物或最终实机验收。
- assets/boot-frames/000.png–079.png；assets/boot.anim、boot.ogg。当前详情图可不使用，后续视频备用。

## 字体与规范
- assets/fonts/NotoSansSC-VF.ttf、NotoSerifSC-VF.ttf：从 Google Fonts 官方仓库下载，附 OFL 与来源记录；用 @font-face 引用，不能依赖云端临时联网。
- [设计规范](DESIGN_RULES.md)、[交给 Claude 的提示词](CLAUDE_PROMPT.md)、[缺失项](MISSING_INPUTS.md)。

## 不公开复制的第三方参考
- 摩点 Fuzzi 教程截图仅转述布局逻辑：Slogan + 大产品图 + 简介 / 核心卖点 / 档位 / 解锁 / 发起方。不复用 Fuzzi 品牌、插画或产品。
- 用户指定视频：https://www.bilibili.com/video/BV1hhao6cEfq/ 。包内不重新分发视频或抽帧。
- 方法参考：https://github.com/OwnDing/open-xiaoai 。没有把整套第三方仓库复制进来。
