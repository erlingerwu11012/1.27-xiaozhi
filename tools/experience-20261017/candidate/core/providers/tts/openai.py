import requests
from core.utils.util import check_model_key
from core.providers.tts.base import TTSProviderBase
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.api_key = config.get("api_key")
        self.api_url = config.get("api_url", "https://api.openai.com/v1/audio/speech")
        self.model = config.get("model", "tts-1")
        if config.get("private_voice"):
            self.voice = config.get("private_voice")
        else:
            self.voice = config.get("voice", "alloy")
        self.response_format = config.get("format", "wav")
        self.audio_file_type = config.get("format", "wav")
        self.aimi_device_gateway = bool(config.get("aimi_device_gateway", False))
        self.aimi_device_service_key = config.get("aimi_device_service_key", "")
        self.aimi_device_context = None

        # 处理空字符串的情况
        speed = config.get("speed", "1.0")
        self.speed = float(speed) if speed else 1.0

        self.output_file = config.get("output_dir", "tmp/")
        model_key_msg = check_model_key("TTS", self.api_key)
        if model_key_msg:
            logger.bind(tag=TAG).error(model_key_msg)

    def set_aimi_device_context(self, context):
        if self.aimi_device_gateway:
            self.aimi_device_context = dict(context)

    def _aimi_headers(self):
        if not self.aimi_device_gateway:
            return {}
        context = self.aimi_device_context
        if not context or not self.aimi_device_service_key:
            raise ValueError("AIMI device gateway requires device context and service key")
        return {
            "X-AIMI-Device-Service-Key": self.aimi_device_service_key,
            "X-AIMI-Device-ID": context["device_id"],
            "X-AIMI-Device-MAC": context.get("mac_address", ""),
            "X-AIMI-Xiaozhi-User-ID": context.get("user_id", ""),
            "X-AIMI-Device-Session-ID": context["session_id"],
        }

    async def text_to_speak(self, text, output_file):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self._aimi_headers())
        data = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "wav",
            "speed": self.speed,
        }
        response = requests.post(self.api_url, json=data, headers=headers)
        if response.status_code == 200:
            if output_file:
                with open(output_file, "wb") as audio_file:
                    audio_file.write(response.content)
            else:
                return response.content
        else:
            raise Exception(
                f"OpenAI TTS请求失败: {response.status_code} - {response.text}"
            )
