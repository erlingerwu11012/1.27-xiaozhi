package xiaozhi.modules.rolepack.util;

import java.util.Arrays;

import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

/**
 * 受控预览媒体的 Range 响应（不暴露磁盘路径）。
 */
public final class HttpRangeResponder {

    private HttpRangeResponder() {
    }

    public static ResponseEntity<byte[]> respond(byte[] data, String contentType, String rangeHeader) {
        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.ACCEPT_RANGES, "bytes");
        headers.set("X-Content-Type-Options", "nosniff");
        MediaType mt = MediaType.parseMediaType(contentType);
        headers.setContentType(mt);
        if (data == null) {
            data = new byte[0];
        }
        if (rangeHeader == null || rangeHeader.isBlank()) {
            headers.setContentLength(data.length);
            return new ResponseEntity<>(data, headers, HttpStatus.OK);
        }
        long total = data.length;
        ParsedRange range = parseBytesRange(rangeHeader, total);
        if (range == null) {
            headers.set(HttpHeaders.CONTENT_RANGE, "bytes */" + total);
            return new ResponseEntity<>(new byte[0], headers, HttpStatus.REQUESTED_RANGE_NOT_SATISFIABLE);
        }
        byte[] slice = Arrays.copyOfRange(data, range.start, range.endExclusive);
        headers.set(HttpHeaders.CONTENT_RANGE,
                "bytes " + range.start + "-" + (range.endExclusive - 1) + "/" + total);
        headers.setContentLength(slice.length);
        return new ResponseEntity<>(slice, headers, HttpStatus.PARTIAL_CONTENT);
    }

    static ParsedRange parseBytesRange(String header, long total) {
        String h = header.trim();
        if (!h.toLowerCase().startsWith("bytes=")) {
            return null;
        }
        String spec = h.substring("bytes=".length()).trim();
        if (spec.contains(",") || spec.isEmpty()) {
            return null;
        }
        int dash = spec.indexOf('-');
        if (dash < 0) {
            return null;
        }
        String startS = spec.substring(0, dash).trim();
        String endS = spec.substring(dash + 1).trim();
        try {
            long start;
            long endInclusive;
            if (startS.isEmpty()) {
                long suffix = Long.parseLong(endS);
                if (suffix <= 0) {
                    return null;
                }
                start = Math.max(0, total - suffix);
                endInclusive = total - 1;
            } else {
                start = Long.parseLong(startS);
                endInclusive = endS.isEmpty() ? total - 1 : Long.parseLong(endS);
            }
            if (start < 0 || start >= total || endInclusive < start) {
                return null;
            }
            if (endInclusive >= total) {
                endInclusive = total - 1;
            }
            return new ParsedRange((int) start, (int) endInclusive + 1);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    record ParsedRange(int start, int endExclusive) {
    }
}
