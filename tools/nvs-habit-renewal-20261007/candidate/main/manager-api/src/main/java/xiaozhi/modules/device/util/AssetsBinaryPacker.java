package xiaozhi.modules.device.util;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/**
 * Assets 分区二进制打包工具
 *
 * 格式说明（全部 little-endian）：
 * - Header (12B): total_files(4B) + checksum(4B) + combined_len(4B)
 * - 目录表: 每项 44B = name(32B) + size(4B) + offset(4B) + width(2B) + height(2B)
 * - 数据区: 每个文件前有 2 字节 ZZ (0x5A, 0x5A)，然后是文件内容
 *
 * 打包规则：
 * - 文件按 (扩展名, 文件名) 字母序排列
 * - 跳过 config.json
 * - index.json 作为普通文件参与打包
 * - checksum = 所有字节有符号累加，取低 16 位
 */
public class AssetsBinaryPacker {

    private static final int HEADER_SIZE = 12;
    private static final int DIR_ENTRY_SIZE = 44;
    private static final int NAME_FIELD_SIZE = 32;
    private static final byte[] ZZ_MARKER = new byte[]{0x5A, 0x5A};
    private static final int ZZ_SIZE = 2;

    /**
     * 打包文件列表为 assets 二进制
     *
     * @param files 文件列表（已排序或未排序均可，内部会重新排序）
     * @return 完整的 assets.bin 字节数组
     */
    public static byte[] pack(List<AssetFile> files) throws IOException {
        // 1. 过滤掉 config.json
        List<AssetFile> filtered = files.stream()
                .filter(f -> !"config.json".equalsIgnoreCase(f.getName()))
                .collect(java.util.stream.Collectors.toList());

        // 2. 按 (扩展名, 文件名) 排序
        filtered.sort(Comparator
                .comparing((AssetFile f) -> getExtension(f.getName()))
                .thenComparing(AssetFile::getName));

        int totalFiles = filtered.size();

        // 3. 构建数据区，计算每个文件的 offset
        ByteArrayOutputStream dataArea = new ByteArrayOutputStream();
        int[] offsets = new int[totalFiles];
        int[] sizes = new int[totalFiles];

        for (int i = 0; i < totalFiles; i++) {
            offsets[i] = dataArea.size();
            byte[] content = filtered.get(i).getData();
            sizes[i] = content.length;
            dataArea.write(ZZ_MARKER);
            dataArea.write(content);
        }

        byte[] dataBytes = dataArea.toByteArray();

        // 4. 构建目录表
        ByteArrayOutputStream dirArea = new ByteArrayOutputStream();
        for (int i = 0; i < totalFiles; i++) {
            AssetFile file = filtered.get(i);
            ByteBuffer entry = ByteBuffer.allocate(DIR_ENTRY_SIZE);
            entry.order(ByteOrder.LITTLE_ENDIAN);

            // name (32 bytes, null-padded)
            byte[] nameBytes = file.getName().getBytes(StandardCharsets.UTF_8);
            byte[] namePadded = new byte[NAME_FIELD_SIZE];
            System.arraycopy(nameBytes, 0, namePadded, 0, Math.min(nameBytes.length, NAME_FIELD_SIZE - 1));
            entry.put(namePadded);

            // size (4 bytes)
            entry.putInt(sizes[i]);

            // offset (4 bytes) — 包含 ZZ 标记的偏移
            entry.putInt(offsets[i]);

            // width (2 bytes)
            entry.putShort(file.getWidth());

            // height (2 bytes)
            entry.putShort(file.getHeight());

            dirArea.write(entry.array());
        }

        byte[] dirBytes = dirArea.toByteArray();

        // 5. combined_len = 目录表 + 数据区
        int combinedLen = dirBytes.length + dataBytes.length;

        // 6. 计算 checksum：对 (目录表 + 数据区) 所有字节有符号累加，取低 16 位
        int checksum = 0;
        for (byte b : dirBytes) {
            checksum += b; // byte 有符号 -128~127
        }
        for (byte b : dataBytes) {
            checksum += b;
        }
        checksum &= 0xFFFF;

        // 7. 写入最终二进制
        ByteArrayOutputStream output = new ByteArrayOutputStream();

        // Header (12 bytes)
        ByteBuffer header = ByteBuffer.allocate(HEADER_SIZE);
        header.order(ByteOrder.LITTLE_ENDIAN);
        header.putInt(totalFiles);
        header.putInt(checksum);
        header.putInt(combinedLen);
        output.write(header.array());

        // 目录表
        output.write(dirBytes);

        // 数据区
        output.write(dataBytes);

        return output.toByteArray();
    }

    /**
     * 获取文件扩展名（不含点号），用于排序
     */
    private static String getExtension(String filename) {
        int dot = filename.lastIndexOf('.');
        if (dot < 0) return "";
        return filename.substring(dot + 1).toLowerCase();
    }

    /**
     * 表示一个待打包的资源文件
     */
    public static class AssetFile {
        private final String name;
        private final byte[] data;
        private short width;
        private short height;

        public AssetFile(String name, byte[] data) {
            this.name = name;
            this.data = data;
            this.width = 0;
            this.height = 0;
        }

        public AssetFile(String name, byte[] data, short width, short height) {
            this.name = name;
            this.data = data;
            this.width = width;
            this.height = height;
        }

        public String getName() { return name; }
        public byte[] getData() { return data; }
        public short getWidth() { return width; }
        public short getHeight() { return height; }
    }
}
