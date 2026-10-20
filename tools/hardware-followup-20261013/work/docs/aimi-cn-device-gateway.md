# AIMI CN internal device gateway

This optional provider mode routes Xiaozhi server traffic through the local
`aimi-cn-gateway` and never gives an OneAPI token to an ESP32 device. It is a
server configuration change to make during deployment; do not place a service
key in an ESP32 firmware image or a tracked YAML file.

Use this shape in the server's private provider configuration, injecting the
service key from its ignored runtime environment/config store:

```yaml
LLM:
  aimi_device:
    type: openai
    base_url: http://127.0.0.1:8761/internal/device/v1
    api_key: unused-local-placeholder
    aimi_device_gateway: true
    aimi_device_service_key: ${AIMI_DEVICE_GATEWAY_SECRET}
    model_name: aimi-chat
ASR:
  aimi_device:
    type: openai
    base_url: http://127.0.0.1:8761/internal/device/v1/audio/transcriptions
    api_key: unused-local-placeholder
    aimi_device_gateway: true
    aimi_device_service_key: ${AIMI_DEVICE_GATEWAY_SECRET}
    model_name: aimi-asr
TTS:
  aimi_device:
    type: openai
    api_url: http://127.0.0.1:8761/internal/device/v1/audio/speech
    api_key: unused-local-placeholder
    aimi_device_gateway: true
    aimi_device_service_key: ${AIMI_DEVICE_GATEWAY_SECRET}
    model: aimi-tts
```

When enabled, the connection handler supplies device id, MAC, optional Xiaozhi
user id and session id. The LLM switches to non-streaming upstream mode because
the current internal device endpoint records one completed request at a time.
`DEVICE_BILLING_ENABLED=false` is the default: device requests are recorded in
`device_usage_records` and never deduct desktop Flux.
