from pathlib import Path
ROOT=Path('E:/github/github_code/all/4.30').resolve()
p=ROOT/'main/boards/common/esp32_camera.cc'
assert p.resolve().is_relative_to(ROOT)
s=p.read_text(encoding='utf-8')
assert 'esp_err_t Esp32Camera::StartUsbHost()' not in s
s=s.replace('    if (!s_first_frame_seen) {','    self->streaming_on_ = true;\n    self->recovery_.OnFrame();\n    if (!s_first_frame_seen) {',1)
s=s.replace('        self->streaming_on_ = true;\n        ESP_LOGI(TAG, "[UVC] Stream resume accepted;','        self->streaming_on_ = false;\n        ESP_LOGI(TAG, "[UVC] Stream resume accepted;')
s=s.replace('        ESP_LOGW(TAG, "[UVC] USB camera disconnected; capture requests will be rejected");','        if (frame_sem_) while (xSemaphoreTake(frame_sem_,0)==pdTRUE) {}\n        self->recovery_.OnDisconnected(esp_timer_get_time()/1000);\n        ESP_LOGW(TAG, "[UVC] USB camera disconnected; capture rejected; bounded recovery scheduled");')
s=s.replace('            ESP_LOGE(TAG, "[UVC] Camera failed to resume:', '            self->recovery_.OnDisconnected(esp_timer_get_time()/1000);\n            ESP_LOGE(TAG, "[UVC] Camera failed to resume:')
a=s.index('    // Do not hard-code endpoint');b=s.index('    usb_started_ = true;',a)
config=s[a:s.index('    esp_err_t err = uvc_streaming_config',a)]
s=s[:a]+'''    esp_err_t err=StartUsbHost();
    if (err!=ESP_OK) {
        ESP_LOGE(TAG,"[UVC] USB host start failed: %s",esp_err_to_name(err));
        cleanup();return;
    }
'''+s[b:]
methods='''esp_err_t Esp32Camera::StartUsbHost() {
'''+config+'''    esp_err_t err=uvc_streaming_config(&config);
    if (err!=ESP_OK)return err;
    err=usb_streaming_state_register(&UsbStreamStateCallback,this);
    if (err!=ESP_OK)return err;
    return usb_streaming_start();
}

void Esp32Camera::RecoveryWorker(void* arg) {
    auto* self=static_cast<Esp32Camera*>(arg);
    while (!self->recovery_stop_.load()) {
        const auto action=self->recovery_.Poll(esp_timer_get_time()/1000);
        if (action==UsbCameraRecovery::Action::kStop) {
            self->streaming_on_=false;
            const esp_err_t result=self->usb_started_?usb_streaming_stop():ESP_OK;
            if (result==ESP_OK)self->usb_started_=false;
            self->streaming_on_=false;
            self->recovery_.Stopped(result==ESP_OK,esp_timer_get_time()/1000);
            ESP_LOGW(TAG,"[UVC] recovery phase=stop result=%s",esp_err_to_name(result));
        } else if (action==UsbCameraRecovery::Action::kStart) {
            const esp_err_t result=self->StartUsbHost();
            if (result==ESP_OK)self->usb_started_=true;
            self->recovery_.Started(result==ESP_OK,esp_timer_get_time()/1000);
            ESP_LOGW(TAG,"[UVC] recovery phase=reenumerate result=%s",esp_err_to_name(result));
        }
        vTaskDelay(pdMS_TO_TICKS(250));
    }
    self->recovery_done_=true;
    vTaskDeleteWithCaps(nullptr);
}

'''
pos=s.index('Esp32Camera::~Esp32Camera()');s=s[:pos]+methods+s[pos:]
s=s.replace('    usb_started_ = true;\n\n    // usb_stream','''    usb_started_ = true;
    recovery_done_=false;
    TaskHandle_t recovery_task=nullptr;
    if (xTaskCreateWithCaps(RecoveryWorker,"usb_cam_recover",4096,this,2,&recovery_task,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)!=pdPASS) {
        recovery_done_=true;
        ESP_LOGE(TAG,"[UVC] recovery worker unavailable: resource_exhausted");
    }

    // usb_stream''')
s=s.replace('    ESP_LOGI(TAG, "[UVC] Stopping USB camera stream");','    ESP_LOGI(TAG, "[UVC] Stopping USB camera stream");\n    recovery_.Close();recovery_stop_=true;\n    while (!recovery_done_.load())vTaskDelay(pdMS_TO_TICKS(10));',1)
s=s.replace('    if (frame_len_ == 0 || !frame_buf_) {','    if (!streaming_on_.load() || frame_len_ == 0 || !frame_buf_) {',1)
p.write_text(s,encoding='utf-8')
print('USB camera recovery integration written')
