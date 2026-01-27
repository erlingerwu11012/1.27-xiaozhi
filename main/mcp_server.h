#ifndef MCP_SERVER_H
#define MCP_SERVER_H

#include <string>
#include <vector>
#include <map>
#include <functional>
#include <variant>
#include <optional>
#include <stdexcept>
#include <thread>
#include <mbedtls/base64.h>

#include <cJSON.h>

/**
 * ImageContent: 处理图片 Base64 编码
 * 优化：确保内存申请和释放逻辑清晰
 */
class ImageContent {
private:
    std::string encoded_data_;
    std::string mime_type_;

    static std::string Base64Encode(const std::string& data) {
        size_t dlen = 0, olen = 0;
        // 第一次调用获取所需长度
        mbedtls_base64_encode(nullptr, 0, &dlen, (const unsigned char*)data.data(), data.size());
        std::string result(dlen, 0);
        // 第二次调用实际编码
        mbedtls_base64_encode((unsigned char*)result.data(), result.size(), &olen, (const unsigned char*)data.data(), data.size());
        // 裁剪掉多余的 \0
        result.resize(olen);
        return result;
    }

public:
    ImageContent(const std::string& mime_type, const std::string& data) 
        : mime_type_(mime_type) {
        encoded_data_ = Base64Encode(data);
    }

    // 转换为 cJSON 对象而不是字符串，减少重复解析开销
    cJSON* to_cjson() const {
        cJSON *json = cJSON_CreateObject();
        cJSON_AddStringToObject(json, "type", "image");
        cJSON_AddStringToObject(json, "mimeType", mime_type_.c_str());
        cJSON_AddStringToObject(json, "data", encoded_data_.c_str());
        return json;
    }

    std::string to_json() const {
        cJSON *json = to_cjson();
        char* json_str = cJSON_PrintUnformatted(json);
        std::string result(json_str);
        cJSON_free(json_str);
        cJSON_Delete(json);
        return result;
    }
};

// 返回值类型别名
using ReturnValue = std::variant<bool, int, std::string, cJSON*, ImageContent*>;

enum PropertyType {
    kPropertyTypeBoolean,
    kPropertyTypeInteger,
    kPropertyTypeString
};

class Property {
private:
    std::string name_;
    PropertyType type_;
    std::variant<bool, int, std::string> value_;
    bool has_default_value_;
    std::optional<int> min_value_;
    std::optional<int> max_value_;

public:
    Property(const std::string& name, PropertyType type)
        : name_(name), type_(type), has_default_value_(false) {}

    template<typename T>
    Property(const std::string& name, PropertyType type, const T& default_value)
        : name_(name), type_(type), has_default_value_(true) {
        value_ = default_value;
    }

    Property(const std::string& name, PropertyType type, int min_value, int max_value)
        : name_(name), type_(type), has_default_value_(false), min_value_(min_value), max_value_(max_value) {
        if (type != kPropertyTypeInteger) throw std::invalid_argument("Range limits only for integers");
    }

    Property(const std::string& name, PropertyType type, int default_value, int min_value, int max_value)
        : name_(name), type_(type), has_default_value_(true), min_value_(min_value), max_value_(max_value) {
        if (type != kPropertyTypeInteger) throw std::invalid_argument("Range limits only for integers");
        value_ = default_value;
    }

    inline const std::string& name() const { return name_; }
    inline PropertyType type() const { return type_; }
    inline bool has_default_value() const { return has_default_value_; }

    template<typename T>
    inline T value() const { return std::get<T>(value_); }

    template<typename T>
    inline void set_value(const T& value) {
        if constexpr (std::is_same_v<T, int>) {
            if (min_value_ && value < *min_value_) throw std::invalid_argument("Value below minimum");
            if (max_value_ && value > *max_value_) throw std::invalid_argument("Value above maximum");
        }
        value_ = value;
    }

    std::string to_json() const {
        cJSON *json = cJSON_CreateObject();
        if (type_ == kPropertyTypeBoolean) {
            cJSON_AddStringToObject(json, "type", "boolean");
            if (has_default_value_) cJSON_AddBoolToObject(json, "default", value<bool>());
        } else if (type_ == kPropertyTypeInteger) {
            cJSON_AddStringToObject(json, "type", "integer");
            if (has_default_value_) cJSON_AddNumberToObject(json, "default", value<int>());
            if (min_value_) cJSON_AddNumberToObject(json, "minimum", *min_value_);
            if (max_value_) cJSON_AddNumberToObject(json, "maximum", *max_value_);
        } else if (type_ == kPropertyTypeString) {
            cJSON_AddStringToObject(json, "type", "string");
            if (has_default_value_) cJSON_AddStringToObject(json, "default", value<std::string>().c_str());
        }
        char *json_str = cJSON_PrintUnformatted(json);
        std::string result(json_str);
        cJSON_free(json_str);
        cJSON_Delete(json);
        return result;
    }
};

class PropertyList {
private:
    std::vector<Property> properties_;

public:
    PropertyList() = default;
    PropertyList(const std::vector<Property>& properties) : properties_(properties) {}
    void AddProperty(const Property& property) { properties_.push_back(property); }

    const Property& operator[](const std::string& name) const {
        for (const auto& p : properties_) if (p.name() == name) return p;
        throw std::runtime_error("Property not found: " + name);
    }

    auto begin() { return properties_.begin(); }
    auto end() { return properties_.end(); }

    std::vector<std::string> GetRequired() const {
        std::vector<std::string> req;
        for (const auto& p : properties_) if (!p.has_default_value()) req.push_back(p.name());
        return req;
    }

    std::string to_json() const {
        cJSON *json = cJSON_CreateObject();
        for (const auto& p : properties_) {
            cJSON *prop_json = cJSON_Parse(p.to_json().c_str());
            cJSON_AddItemToObject(json, p.name().c_str(), prop_json);
        }
        char *json_str = cJSON_PrintUnformatted(json);
        std::string result(json_str);
        cJSON_free(json_str);
        cJSON_Delete(json);
        return result;
    }
};

class McpTool {
private:
    std::string name_;
    std::string description_;
    PropertyList properties_;
    std::function<ReturnValue(const PropertyList&)> callback_;
    bool user_only_ = false;

public:
    McpTool(const std::string& name, const std::string& desc, const PropertyList& props, std::function<ReturnValue(const PropertyList&)> cb)
        : name_(name), description_(desc), properties_(props), callback_(cb) {}

    void set_user_only(bool val) { user_only_ = val; }
    inline const std::string& name() const { return name_; }
    inline bool user_only() const { return user_only_; }
    inline const PropertyList& properties() const { return properties_; }

    std::string to_json() const {
        cJSON *json = cJSON_CreateObject();
        cJSON_AddStringToObject(json, "name", name_.c_str());
        cJSON_AddStringToObject(json, "description", description_.c_str());
        
        cJSON *input_schema = cJSON_CreateObject();
        cJSON_AddStringToObject(input_schema, "type", "object");
        cJSON_AddItemToObject(input_schema, "properties", cJSON_Parse(properties_.to_json().c_str()));
        
        auto required = properties_.GetRequired();
        if (!required.empty()) {
            cJSON *req_arr = cJSON_CreateArray();
            for (const auto& s : required) cJSON_AddItemToArray(req_arr, cJSON_CreateString(s.c_str()));
            cJSON_AddItemToObject(input_schema, "required", req_arr);
        }
        cJSON_AddItemToObject(json, "inputSchema", input_schema);

        if (user_only_) {
            cJSON *ann = cJSON_CreateObject();
            cJSON *aud = cJSON_CreateArray();
            cJSON_AddItemToArray(aud, cJSON_CreateString("user"));
            cJSON_AddItemToObject(ann, "audience", aud);
            cJSON_AddItemToObject(json, "annotations", ann);
        }
        
        char *json_str = cJSON_PrintUnformatted(json);
        std::string result(json_str);
        cJSON_free(json_str);
        cJSON_Delete(json);
        return result;
    }

    std::string Call(const PropertyList& props) {
        ReturnValue val = callback_(props);
        cJSON* root = cJSON_CreateObject();
        cJSON* content_arr = cJSON_CreateArray();

        if (std::holds_alternative<ImageContent*>(val)) {
            auto img = std::get<ImageContent*>(val);
            cJSON_AddItemToArray(content_arr, img->to_cjson());
            delete img; // 回调创建的指针在这里释放
        } else {
            cJSON* text_obj = cJSON_CreateObject();
            cJSON_AddStringToObject(text_obj, "type", "text");
            if (std::holds_alternative<std::string>(val)) {
                cJSON_AddStringToObject(text_obj, "text", std::get<std::string>(val).c_str());
            } else if (std::holds_alternative<bool>(val)) {
                cJSON_AddStringToObject(text_obj, "text", std::get<bool>(val) ? "true" : "false");
            } else if (std::holds_alternative<int>(val)) {
                cJSON_AddStringToObject(text_obj, "text", std::to_string(std::get<int>(val)).c_str());
            } else if (std::holds_alternative<cJSON*>(val)) {
                cJSON* raw_json = std::get<cJSON*>(val);
                char* s = cJSON_PrintUnformatted(raw_json);
                cJSON_AddStringToObject(text_obj, "text", s);
                cJSON_free(s);
                cJSON_Delete(raw_json);
            }
            cJSON_AddItemToArray(content_arr, text_obj);
        }
        cJSON_AddItemToObject(root, "content", content_arr);
        cJSON_AddBoolToObject(root, "isError", false);

        char* final_s = cJSON_PrintUnformatted(root);
        std::string result(final_s);
        cJSON_free(final_s);
        cJSON_Delete(root);
        return result;
    }
};

class McpServer {
public:
    static McpServer& GetInstance() {
        static McpServer instance;
        return instance;
    }

    void AddCommonTools();
    void AddUserOnlyTools();
    void AddTool(McpTool* tool);
    void AddTool(const std::string& name, const std::string& desc, const PropertyList& props, std::function<ReturnValue(const PropertyList&)> cb);
    void AddUserOnlyTool(const std::string& name, const std::string& desc, const PropertyList& props, std::function<ReturnValue(const PropertyList&)> cb);
    void ParseMessage(const cJSON* json);
    void ParseMessage(const std::string& message);

private:
    McpServer();
    ~McpServer();
    void ParseCapabilities(const cJSON* capabilities);
    void ReplyResult(int id, const std::string& result);
    void ReplyError(int id, const std::string& message);
    void GetToolsList(int id, const std::string& cursor, bool list_user_only_tools);
    void DoToolCall(int id, const std::string& tool_name, const cJSON* tool_arguments);

    std::vector<McpTool*> tools_;
};

#endif // MCP_SERVER_H