package xiaozhi.modules.model.util;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;

import xiaozhi.common.utils.JsonUtils;

/**
 * 将 MCP 工具的 JSON Schema 格式的 input_schema 转换为前端可渲染的配置项（fields）。
 * 前端期望的 field 结构：key, label, type, default。
 */
public final class JsonSchemaToFieldsConverter {

    private static final String KEY_PROPERTIES = "properties";
    private static final String KEY_REQUIRED = "required";
    private static final String KEY_TYPE = "type";
    private static final String KEY_DESCRIPTION = "description";
    private static final String KEY_DEFAULT = "default";
    private static final String CONFIG_FIELD_MARKER = "config_field: true";

    private JsonSchemaToFieldsConverter() {
    }

    /**
     * 将 input_schema（JSON Schema 格式）中的 properties 转为 fields 列表。
     *
     * @param inputSchema input_schema 对象，通常包含 type="object"、properties 和 required
     * @return 前端可用的 fields 列表，每项包含 key, label, type, default, required, configField
     */
    @SuppressWarnings("unchecked")
    public static List<Map<String, Object>> fromInputSchema(Map<String, Object> inputSchema) {
        List<Map<String, Object>> fields = new ArrayList<>();
        if (inputSchema == null) {
            return fields;
        }
        Object props = inputSchema.get(KEY_PROPERTIES);
        if (!(props instanceof Map)) {
            return fields;
        }
        Map<String, Object> properties = (Map<String, Object>) props;
        List<String> requiredList = new ArrayList<>();
        Object requiredObj = inputSchema.get(KEY_REQUIRED);
        if (requiredObj instanceof List) {
            for (Object o : (List<?>) requiredObj) {
                if (o != null) {
                    requiredList.add(o.toString());
                }
            }
        }
        for (Map.Entry<String, Object> entry : properties.entrySet()) {
            String propName = entry.getKey();
            Object propVal = entry.getValue();
            if (!(propVal instanceof Map)) {
                continue;
            }
            Map<String, Object> propSchema = (Map<String, Object>) propVal;
            String label = labelFromSchema(propName, propSchema);
            Map<String, Object> field = new LinkedHashMap<>();
            field.put("key", propName);
            field.put("label", label);
            field.put("type", typeFromSchema(propSchema));
            field.put("default", defaultFromSchema(propSchema));
            field.put("required", requiredList.contains(propName));
            field.put("configField", label != null && label.contains(CONFIG_FIELD_MARKER));
            fields.add(field);
        }
        return fields;
    }

    /**
     * 将 fields 列表序列化为前端/数据库使用的 JSON 字符串（与 ModelProviderDTO.fields 格式一致）。
     */
    public static String toFieldsJson(List<Map<String, Object>> fields) {
        if (fields == null || fields.isEmpty()) {
            return "[]";
        }
        return JsonUtils.toJsonString(fields);
    }

    private static String labelFromSchema(String propName, Map<String, Object> propSchema) {
        Object desc = propSchema.get(KEY_DESCRIPTION);
        if (desc != null && StringUtils.isNotBlank(desc.toString())) {
            return desc.toString();
        }
        return toLabel(propName);
    }

    private static String toLabel(String key) {
        if (StringUtils.isBlank(key)) {
            return key;
        }
        return key.replace("_", " ").replace("-", " ");
    }

    private static String typeFromSchema(Map<String, Object> propSchema) {
        Object type = propSchema.get(KEY_TYPE);
        if (type == null) {
            return "string";
        }
        String t = type.toString().toLowerCase();
        switch (t) {
            case "integer":
            case "number":
                return "number";
            case "boolean":
            case "bool":
                return "boolean";
            case "array":
                return "array";
            case "object":
                return "json";
            case "string":
            default:
                return "string";
        }
    }

    private static Object defaultFromSchema(Map<String, Object> propSchema) {
        if (propSchema.containsKey(KEY_DEFAULT)) {
            return propSchema.get(KEY_DEFAULT);
        }
        String type = typeFromSchema(propSchema);
        switch (type) {
            case "number":
                return 0;
            case "boolean":
            case "bool":
                return false;
            case "array":
                return List.of();
            case "json":
                return Map.of();
            case "string":
            default:
                return "";
        }
    }
}
