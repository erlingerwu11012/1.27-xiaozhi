package xiaozhi.modules.officialtts.engine;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Structural WAV validation for clone source audio. */
public final class OfficialTtsAudioInspector {
    public static final class Result {
        public final int sampleRate;
        public final int channels;
        public final int bits;
        public final int durationMs;
        public final String mime;

        public Result(int sampleRate, int channels, int bits, int durationMs, String mime) {
            this.sampleRate = sampleRate;
            this.channels = channels;
            this.bits = bits;
            this.durationMs = durationMs;
            this.mime = mime;
        }
    }

    private OfficialTtsAudioInspector() {
    }

    public static void inspectExportWav(byte[] data) {
        if (data == null || data.length < 12) {
            throw new IllegalArgumentException("audio_too_small");
        }
        if (!ascii(data, 0, 4).equals("RIFF") || !ascii(data, 8, 4).equals("WAVE")) {
            throw new IllegalArgumentException("audio_not_wav");
        }
    }

    public static Result inspectWav(byte[] data) {
        if (data == null || data.length < 44) {
            throw new IllegalArgumentException("audio_too_small");
        }
        if (!ascii(data, 0, 4).equals("RIFF") || !ascii(data, 8, 4).equals("WAVE")) {
            throw new IllegalArgumentException("audio_not_wav");
        }
        int pos = 12;
        int channels = 0, sampleRate = 0, bits = 0, dataSize = 0;
        boolean fmt = false;
        while (pos + 8 <= data.length) {
            String id = ascii(data, pos, 4);
            int size = le32(data, pos + 4);
            int next = pos + 8 + size + (size & 1);
            if ("fmt ".equals(id)) {
                if (size < 16) {
                    throw new IllegalArgumentException("wav_fmt_invalid");
                }
                int format = le16(data, pos + 8);
                channels = le16(data, pos + 10);
                sampleRate = le32(data, pos + 12);
                bits = le16(data, pos + 22);
                if (format != 1) {
                    throw new IllegalArgumentException("wav_not_pcm");
                }
                fmt = true;
            } else if ("data".equals(id)) {
                dataSize = size;
            }
            if (next <= pos) {
                break;
            }
            pos = next;
        }
        if (!fmt || dataSize <= 0 || channels < 1 || channels > 2 || bits != 16) {
            throw new IllegalArgumentException("wav_pcm16_required");
        }
        if (!(sampleRate == 16000 || sampleRate == 22050 || sampleRate == 24000 || sampleRate == 48000)) {
            throw new IllegalArgumentException("wav_sample_rate");
        }
        int bytesPerMs = Math.max(1, (sampleRate * channels * (bits / 8)) / 1000);
        int durationMs = (dataSize * 1000) / (sampleRate * channels * (bits / 8));
        if (durationMs < 3000 || durationMs > 30000) {
            throw new IllegalArgumentException("wav_duration_3_to_30s:" + durationMs);
        }
        if (bytesPerMs < 1) {
            throw new IllegalArgumentException("wav_duration_3_to_30s");
        }
        return new Result(sampleRate, channels, bits, durationMs, "audio/wav");
    }

    public static byte[] silentPcm16Wav(int seconds, int sampleRate) {
        int dataSize = seconds * sampleRate * 2;
        ByteBuffer buf = ByteBuffer.allocate(44 + dataSize).order(ByteOrder.LITTLE_ENDIAN);
        buf.put("RIFF".getBytes(StandardCharsets.US_ASCII));
        buf.putInt(36 + dataSize);
        buf.put("WAVE".getBytes(StandardCharsets.US_ASCII));
        buf.put("fmt ".getBytes(StandardCharsets.US_ASCII));
        buf.putInt(16);
        buf.putShort((short) 1);
        buf.putShort((short) 1);
        buf.putInt(sampleRate);
        buf.putInt(sampleRate * 2);
        buf.putShort((short) 2);
        buf.putShort((short) 16);
        buf.put("data".getBytes(StandardCharsets.US_ASCII));
        buf.putInt(dataSize);
        buf.put(new byte[dataSize]);
        return Arrays.copyOf(buf.array(), buf.capacity());
    }

    /**
     * 上游流式合成返回的 WAV 常把 RIFF/data 长度写成 0x7FFFFFFF 占位，
     * 导致播放器读不出时长甚至无法播放。此处按实际字节数就地修正。
     */
    public static byte[] normalizeWav(byte[] data) {
        if (data == null || data.length < 44) {
            return data;
        }
        if (!ascii(data, 0, 4).equals("RIFF") || !ascii(data, 8, 4).equals("WAVE")) {
            return data;
        }
        int pos = 12;
        while (pos + 8 <= data.length) {
            String id = ascii(data, pos, 4);
            long size = le32u(data, pos + 4);
            if ("data".equals(id)) {
                int avail = data.length - (pos + 8);
                if (size != avail) {
                    putLe32(data, pos + 4, avail);
                    putLe32(data, 4, data.length - 8);
                }
                return data;
            }
            if (pos + 8 + size > data.length) {
                break;
            }
            pos += (int) (8 + size + (size & 1));
        }
        return data;
    }

    private static String ascii(byte[] data, int off, int n) {
        return new String(data, off, n, StandardCharsets.US_ASCII);
    }

    private static long le32u(byte[] data, int off) {
        return (data[off] & 0xffL) | ((data[off + 1] & 0xffL) << 8)
                | ((data[off + 2] & 0xffL) << 16) | ((data[off + 3] & 0xffL) << 24);
    }

    private static void putLe32(byte[] data, int off, int value) {
        data[off] = (byte) (value & 0xff);
        data[off + 1] = (byte) ((value >> 8) & 0xff);
        data[off + 2] = (byte) ((value >> 16) & 0xff);
        data[off + 3] = (byte) ((value >> 24) & 0xff);
    }

    private static int le16(byte[] data, int off) {
        return (data[off] & 0xff) | ((data[off + 1] & 0xff) << 8);
    }

    private static int le32(byte[] data, int off) {
        return (data[off] & 0xff) | ((data[off + 1] & 0xff) << 8)
                | ((data[off + 2] & 0xff) << 16) | ((data[off + 3] & 0xff) << 24);
    }
}
