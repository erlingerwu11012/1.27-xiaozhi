from pathlib import Path
p=Path('main/audio/audio_service.cc');s=p.read_text();s=s.replace('ESP_LOGW(TAG, "Encode queue full, dropping frame");','''const int64_t oldest_us = audio_encode_queue_.empty() ? 0 : audio_encode_queue_.front()->upload_created_us;
        ESP_LOGW(TAG, "Encode queue full, dropping frame encode_q=%u send_q=%u oldest_ms=%lld generation=%lu",
            (unsigned)audio_encode_queue_.size(), (unsigned)audio_send_queue_.size(),
            (long long)(oldest_us > 0 ? (esp_timer_get_time()-oldest_us)/1000 : 0),
            (unsigned long)upload_generation_.load(std::memory_order_acquire));''');p.write_text(s)
