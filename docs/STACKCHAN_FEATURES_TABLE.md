# StackChan 表情与交互功能对照表

本文档汇总 StackChan 原版（stack-chan 仓库）的表情、动画、装饰器、触摸与按钮等能力，供 1.27-xiaozhi 表情与字幕改进参考。

---

## 一、表情（Face）结构

### 1.1 面部部件布局（simple-face.ts）

| 部件     | 位置 (cx, cy) | 尺寸/参数          | 说明                    |
|----------|---------------|---------------------|-------------------------|
| 左眼     | (90, 93)      | 半径 8              | 可随视线偏移 gazeX/Y     |
| 右眼     | (230, 96)     | 半径 8              | 同上                    |
| 嘴       | (160, 148)    | 闭 w=90 h=6, 开 w=50 h=58 | 随 mouth.open 变化   |

### 1.2 情绪（Emotion）及眼部表现

| 情绪       | 眼皮形状 / 表现                         |
|------------|-----------------------------------------|
| NEUTRAL    | 标准矩形眼皮                             |
| ANGRY      | 斜切眼皮（左高右低或反之）               |
| SAD        | 斜切眼皮（与 ANGRY 方向相反）           |
| SLEEPY     | 半闭眼（约高度 50%）                     |
| HAPPY      | 上下分层眼皮（上 60% / 下 40%）         |
| DOUBTFUL   | （由 renderer-base 定义，simple-face 同 default） |
| COLD / HOT | （扩展情绪，部分 mod 使用）             |

---

## 二、动态调节器（Modifier）

| 名称         | 参数                     | 功能描述                     |
|--------------|--------------------------|------------------------------|
| **Blink**    | openMin 400–5000 ms<br>closeMin 200–400 ms | 随机眨眼，眼睛 open 在 0.2–1.0 间变化 |
| **Breath**   | duration 6000 ms         | 呼吸感，约 6 秒周期，face.breath 量化 |
| **Saccade**  | updateMin 300 ms<br>updateMax 2000 ms<br>gain 0.2 | 眼动微移， gazeX/Y 小幅随机变化 |

---

## 三、装饰器（Decorator）

| 装饰器          | 功能说明                     |
|-----------------|------------------------------|
| **Balloon**     | 圆角气泡字幕，可水平滚动长文本，theme.secondary 背景、黑字 |
| **Bubble**      | 气泡动画，多圆形向上飘动     |
| **Heart**       | 心形装饰，带缩放动画         |
| **Angry**       | 生气符号（斜线交叉），带缩放 |
| **Pale**        | 竖线“冷汗”下落动画           |
| **Sweat**       | 汗滴形状下落动画             |

---

## 四、触摸（Touch）

| 回调         | 说明                         |
|--------------|------------------------------|
| onTouchBegan | 触摸开始 (x, y, ticks)       |
| onTouchMoved | 触摸移动                     |
| onTouchEnded | 触摸结束                     |

- 采样：约 16 ms 轮询（ECMA-419 或 legacy）
- 默认由 Touch 类提供，需在应用侧赋值回调

---

## 五、按钮（Button）反馈

| 按钮   | 默认行为（on-robot-created）          |
|--------|--------------------------------------|
| **A**  | 切换 look around，显示 "looking" / "look away" 气泡 |
| **B**  | 测试动作：左→右→下→上→前，显示 "moving..." |
| **C**  | 切换主/次主题色（黑白互换）           |

---

## 六、Robot API 摘要

| 方法/属性       | 说明                       |
|-----------------|----------------------------|
| setEmotion()    | 设置情绪                   |
| setColor()      | 设置 primary/secondary 色   |
| showBalloon()   | 显示气泡字幕               |
| hideBalloon()   | 隐藏气泡字幕               |
| lookAt()        | 设置注视点                 |
| lookAway()      | 取消注视                   |
| say()           | TTS 说话，嘴随 volume 开合  |
| setMouthOpen()  | 直接设置嘴开合 0–1          |
| useRenderer()   | 切换渲染器                 |
| button / touch  | 访问按钮与触摸实例         |

---

## 七、与 1.27-xiaozhi 的对应关系

| StackChan 能力         | 1.27-xiaozhi 实现                     |
|------------------------|---------------------------------------|
| 表情渲染               | procedural_emote + emote_display      |
| 字幕气泡               | 浅蓝背景气泡 + 黑字                   |
| 情绪                   | procedural 表情切换                   |
| 触摸/按钮              | 取决于硬件与上层应用                  |

---

*文档由 StackChan 源码分析生成，主要参考：simple-face.ts, modifier.ts, decorator.ts, touch.ts, robot.ts, on-robot-created.ts*
