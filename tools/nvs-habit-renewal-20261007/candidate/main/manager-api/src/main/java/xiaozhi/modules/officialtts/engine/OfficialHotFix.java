package xiaozhi.modules.officialtts.engine;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Converts platform simplified hot_fix dictionaries into the official Aliyun
 * CosyVoice HTTP object: {"replace":[{k:v}],"pronunciation":[{k:pinyin}]}.
 */
public final class OfficialHotFix {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private OfficialHotFix() {
    }

    public static Object toOfficial(Object raw) {
        if (raw == null) {
            return null;
        }
        Object parsed = raw;
        if (raw instanceof String s) {
            String trimmed = s.trim();
            if (trimmed.isEmpty()) {
                return null;
            }
            try {
                parsed = MAPPER.readValue(trimmed, new TypeReference<Map<String, Object>>() {
                });
            } catch (Exception e) {
                throw new IllegalArgumentException("hot_fix_must_be_object");
            }
        }
        if (!(parsed instanceof Map<?, ?> map) || map.isEmpty()) {
            if (parsed instanceof Map<?, ?>) {
                return null;
            }
            throw new IllegalArgumentException("hot_fix_must_be_object");
        }
        Map<String, Object> obj = new LinkedHashMap<>();
        for (Map.Entry<?, ?> e : map.entrySet()) {
            if (!(e.getKey() instanceof String k)) {
                throw new IllegalArgumentException("hot_fix_must_be_object");
            }
            obj.put(k, e.getValue());
        }
        boolean official = obj.containsKey("replace") || obj.containsKey("pronunciation");
        if (official) {
            for (String key : obj.keySet()) {
                if (!"replace".equals(key) && !"pronunciation".equals(key)) {
                    throw new IllegalArgumentException("hot_fix_unknown_field");
                }
            }
            Map<String, Object> out = new LinkedHashMap<>();
            if (obj.containsKey("replace")) {
                out.put("replace", pairArray(obj.get("replace")));
            }
            if (obj.containsKey("pronunciation")) {
                out.put("pronunciation", pairArray(obj.get("pronunciation")));
            }
            return out;
        }
        List<Map<String, String>> replace = new ArrayList<>();
        for (Map.Entry<String, Object> e : obj.entrySet()) {
            if (!(e.getValue() instanceof String v) || e.getKey() == null || e.getKey().isBlank()) {
                throw new IllegalArgumentException("hot_fix_value_must_be_string");
            }
            replace.add(Map.of(e.getKey(), v));
        }
        return Map.of("replace", replace);
    }

    private static List<Map<String, String>> pairArray(Object raw) {
        if (!(raw instanceof List<?> arr)) {
            throw new IllegalArgumentException("hot_fix_rules_must_be_array");
        }
        List<Map<String, String>> out = new ArrayList<>();
        for (Object item : arr) {
            if (!(item instanceof Map<?, ?> m) || m.size() != 1) {
                throw new IllegalArgumentException("hot_fix_rule_must_be_single_key_object");
            }
            Map.Entry<?, ?> e = m.entrySet().iterator().next();
            if (!(e.getKey() instanceof String k) || !(e.getValue() instanceof String v)) {
                throw new IllegalArgumentException("hot_fix_value_must_be_string");
            }
            out.add(Map.of(k, v));
        }
        return out;
    }
}
