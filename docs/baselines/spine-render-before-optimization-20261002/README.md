# 4.30 固件：绘制、屏幕提交与双核优化前的本地回滚点

日期：2026-10-02（Asia/Shanghai）。本回滚点只保存在本地，不推送远端。

保留当前工作目录的已跟踪修改、删除及未忽略的新文件。包含此前加入的 SPINEPERF / LCDPERF 分段诊断。build 由用户删除，是可重新生成的目录，不纳入 Git。

编译配置快照：sdkconfig.snapshot、dependencies.lock.snapshot。它们用于需要时恢复根目录同名文件；ESP-IDF 为本机 E:/Espressif/frameworks/esp-idf-v5.5.4，目标 ESP-BOX-3 / ESP32-S3、240 MHz、16 MB Flash、Octal PSRAM 80 MHz、320x320 ST7796、LCD SPI 配置 30 MHz。

已测基线（统计窗口有语音和字幕活动，不是严格单变量测试）：
- hero_064_s01h_bg_512：2～3 FPS；约63秒 engine=246.414 ms、draw=234.840 ms、SPI=40.077 ms。
- hero_025_bg_512：约63秒 10 FPS、engine=58.136 ms、draw=50.538 ms、SPI=34.702 ms；约93秒 engine=54.519 ms、draw=47.460 ms、SPI=32.697 ms。
- 动作及附件更新 <约2 ms；主要开销在软件绘制及屏幕提交。

后续目标：优化普通图片和纹理读取、屏幕提交流水线、评估 Core0 分担；保持语音、摄像头、在线角色包及已有功能。性能提升须真机验证。

请优先在单独分支/目录检出本地标签 baseline/4.30-before-render-optimization-20261002，避免覆盖尚未保存的新工作。该标签指向保存本文件的提交。
