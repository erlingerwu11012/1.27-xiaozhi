package xiaozhi.modules.model.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import lombok.Data;

/**
 * MCP 统一网关配置属性。
 * 智控台“刷新 MCP 工具库”会请求 getListToolsUrl()，解析 JSON 数组（name, description, input_schema）并合并到插件列表。
 */
@Data
@Component
@ConfigurationProperties(prefix = "mcp.gateway")
public class McpGatewayProperties {

    /**
     * 网关基础地址，默认与 xiaozhi_mcp_gateway 一致（如 http://127.0.0.1:8123）。
     * list-tools 接口为 {base-url}/list-tools，返回 JSON 数组。
     */
    private String baseUrl = "http://127.0.0.1:8123";

    /**
     * 是否启用 MCP 工具发现
     */
    private boolean enabled = true;

    /**
     * 返回 MCP 网关工具发现接口完整 URL（与网关 /list-tools 约定一致）。
     */
    public String getListToolsUrl() {
        String base = baseUrl == null ? "" : baseUrl.trim();
        if (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        return base + "/list-tools";
    }
}
