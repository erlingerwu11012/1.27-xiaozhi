#include "mcp_permission.h"

bool McpCheckPermission(const std::string& uid, McpPermission perm, std::string& out_error) {
    if (uid == "guest") {
        if (perm == McpPermission::kGeneralChat) {
            return true;
        }
        out_error = "需要主人授权后才能使用此功能";
        return false;
    }
    // default 和注册用户拥有全部权限
    return true;
}
