package xiaozhi.modules.device.controller;

import java.nio.charset.StandardCharsets;
import java.util.TimeZone;

import org.apache.commons.lang3.StringUtils;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.ObjectMapper;

import io.swagger.v3.oas.annotations.Hidden;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.enums.ParameterIn;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.SneakyThrows;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.modules.device.dto.DeviceReportReqDTO;
import xiaozhi.modules.device.dto.DeviceReportRespDTO;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.device.util.MacAddressUtils;
import xiaozhi.modules.device.vo.OtaStatusVO;
import xiaozhi.modules.sys.service.SysParamsService;

@Tag(name = "设备管理", description = "OTA 相关接口")
@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/ota/")
public class OTAController {
    private final DeviceService deviceService;
    private final SysParamsService sysParamsService;

    @Operation(summary = "OTA版本和设备激活状态检查")
    @PostMapping
    public ResponseEntity<String> checkOTAVersion(
            @RequestBody(required = false) String rawBody,
            @Parameter(name = "Device-Id", description = "设备唯一标识", required = false, in = ParameterIn.HEADER) @RequestHeader(value = "Device-Id", required = false) String deviceId,
            @Parameter(name = "Client-Id", description = "客户端标识", required = false, in = ParameterIn.HEADER) @RequestHeader(value = "Client-Id", required = false) String clientId,
            @Parameter(name = "Authorization", description = "Bearer <device_auth_key|wss_token>", required = false, in = ParameterIn.HEADER) @RequestHeader(value = "Authorization", required = false) String authorization,
            @Parameter(name = "X-Activation-Code", description = "绑定后首次兑换 bootstrap", required = false, in = ParameterIn.HEADER) @RequestHeader(value = "X-Activation-Code", required = false) String activationCode) {
        // 无 Device-Id 或 body 为空：返回配置 JSON（websocket + firmware），不报错
        if (StringUtils.isBlank(deviceId) || StringUtils.isBlank(rawBody)) {
            try {
                return createJsonResponse(buildOtaStatus());
            } catch (Exception e) {
                log.warn("POST /ota/ 构建配置失败: {}", e.getMessage());
                return createJsonResponse(buildDefaultOtaStatus());
            }
        }
        DeviceReportReqDTO deviceReportReqDTO = null;
        try {
            com.fasterxml.jackson.databind.ObjectMapper mapper = new com.fasterxml.jackson.databind.ObjectMapper();
            mapper.configure(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
            deviceReportReqDTO = mapper.readValue(rawBody, DeviceReportReqDTO.class);
        } catch (Exception e) {
            log.warn("POST /ota/ 请求体 JSON 解析失败，返回配置 JSON: {}", e.getMessage());
            return createJsonResponse(buildOtaStatus());
        }
        if (deviceReportReqDTO == null) {
            return createJsonResponse(buildOtaStatus());
        }
        // 兼容：旧/全新固件可能没有上报 application 字段，
        // 但我们仍需要进入激活码生成流程以驱动配网。
        if (deviceReportReqDTO.getApplication() == null) {
            DeviceReportReqDTO.Application app = new DeviceReportReqDTO.Application();
            app.setVersion("0.0.0");
            deviceReportReqDTO.setApplication(app);
        }
        if (StringUtils.isBlank(clientId)) {
            clientId = deviceId;
        }
        if (!MacAddressUtils.isValid(deviceId)) {
            return createResponse(DeviceReportRespDTO.createError("Invalid device ID"));
        }
        // 统一规范化 MAC 后进入绑定查询/签发流程
        String canonicalDeviceId = MacAddressUtils.toCanonical(deviceId);
        try {
            return createResponse(deviceService.checkDeviceActive(
                    canonicalDeviceId, clientId, deviceReportReqDTO, authorization, activationCode));
        } catch (Exception e) {
            // token 签发/处理失败时返回明确错误，绝不伪造成功响应
            log.error("POST /ota/ 设备激活检查异常: {}", e.getMessage());
            return createResponse(DeviceReportRespDTO.createError("OTA 处理失败"));
        }
    }

    @Operation(summary = "设备快速检查激活状态")
    @PostMapping("activate")
    public ResponseEntity<String> activateDevice(
            @RequestBody(required = false) String rawBody,
            @Parameter(name = "Device-Id", description = "设备唯一标识", required = true, in = ParameterIn.HEADER) @RequestHeader("Device-Id") String deviceId,
            @Parameter(name = "Client-Id", description = "客户端标识", required = false, in = ParameterIn.HEADER) @RequestHeader(value = "Client-Id", required = false) String clientId) {
        if (StringUtils.isBlank(deviceId)) {
            return ResponseEntity.status(202).body("{\"status\":\"pending\"}");
        }
        DeviceEntity device = deviceService.getDeviceByMacAddress(deviceId);
        if (device == null) {
            return ResponseEntity.status(202).body("{\"status\":\"pending\"}");
        }
        return ResponseEntity.ok("{\"status\":\"success\"}");
    }

    @GetMapping
    @Hidden
    @SneakyThrows
    public ResponseEntity<String> getOTA() {
        try {
            return createJsonResponse(buildOtaStatus());
        } catch (Exception e) {
            log.error("GET /ota/ 异常，返回默认 JSON 避免 500", e);
            return createJsonResponse(buildDefaultOtaStatus());
        }
    }

    /**
     * 构建 OTA 状态，返回 WebSocket 配置供设备连接，配置缺失时使用默认值，绝不抛异常
     */
    private OtaStatusVO buildOtaStatus() {
        String wsUrl = getConfigValue(Constant.SERVER_WEBSOCKET, true);
        String otaUrl = getConfigValue(Constant.SERVER_OTA, true);

        // WebSocket 配置：优先使用 sys_params，否则使用默认
        String resolvedWsUrl = (StringUtils.isNotBlank(wsUrl) && !"null".equals(wsUrl))
                ? (wsUrl.contains(";") ? wsUrl.split(";")[0].trim() : wsUrl)
                : "ws://xiaozhi.server.com:8000/xiaozhi/v1/";
        OtaStatusVO.WebsocketConfig websocket = new OtaStatusVO.WebsocketConfig(resolvedWsUrl, "", 2);

        // 构建固件 URL：格式 {otaBase}/otaMag/download/placeholder
        String firmwareUrl;
        if (StringUtils.isNotBlank(otaUrl) && !"null".equals(otaUrl) && otaUrl.contains("/ota/")) {
            firmwareUrl = otaUrl.replace("/ota/", "/otaMag/download/") + "placeholder";
        } else {
            firmwareUrl = Constant.INVALID_FIRMWARE_URL;
        }

        String version = "2.0.5";
        OtaStatusVO.FirmwareConfig firmware = new OtaStatusVO.FirmwareConfig(version, firmwareUrl);

        String message = "OTA success";
        if (StringUtils.isBlank(wsUrl) || "null".equals(wsUrl)) {
            message = "OTA接口配置不完整，请配置 server.websocket";
        } else if (StringUtils.isBlank(otaUrl) || "null".equals(otaUrl)) {
            message = "OTA接口配置不完整，请配置 server.ota";
        }

        OtaStatusVO.ServerTime serverTime = buildServerTime();
        return new OtaStatusVO(message, serverTime, websocket, firmware);
    }

    private OtaStatusVO buildDefaultOtaStatus() {
        OtaStatusVO.ServerTime serverTime = buildServerTime();
        OtaStatusVO.WebsocketConfig websocket = new OtaStatusVO.WebsocketConfig(
                "ws://xiaozhi.server.com:8000/xiaozhi/v1/", "", 2);
        OtaStatusVO.FirmwareConfig firmware = new OtaStatusVO.FirmwareConfig("2.0.5",
                Constant.INVALID_FIRMWARE_URL);
        return new OtaStatusVO("OTA接口运行中，请完善配置", serverTime, websocket, firmware);
    }

    private OtaStatusVO.ServerTime buildServerTime() {
        long ts = System.currentTimeMillis();
        TimeZone tz = TimeZone.getTimeZone("Asia/Shanghai");
        int offsetMinutes = tz.getOffset(ts) / (60 * 1000);
        return new OtaStatusVO.ServerTime(ts, "Asia/Shanghai", offsetMinutes);
    }

    /**
     * 获取配置：优先 sys_params，否则环境变量
     */
    private String getConfigValue(String paramCode, boolean fromCache) {
        try {
            String v = sysParamsService.getValue(paramCode, fromCache);
            if (StringUtils.isBlank(v) || "null".equals(v)) {
                String envKey = paramCode.replace(".", "_").toUpperCase();
                v = System.getenv(envKey);
            }
            return v;
        } catch (Exception e) {
            log.warn("获取配置 {} 失败: {}", paramCode, e.getMessage());
            return null;
        }
    }

    @SneakyThrows
    private ResponseEntity<String> createJsonResponse(OtaStatusVO vo) {
        ObjectMapper objectMapper = new ObjectMapper();
        objectMapper.setSerializationInclusion(JsonInclude.Include.NON_NULL);
        String json = objectMapper.writeValueAsString(vo);
        byte[] jsonBytes = json.getBytes(StandardCharsets.UTF_8);
        return ResponseEntity
                .ok()
                .contentType(MediaType.APPLICATION_JSON)
                .contentLength(jsonBytes.length)
                .body(json);
    }

    @SneakyThrows
    private ResponseEntity<String> createResponse(DeviceReportRespDTO deviceReportRespDTO) {
        ObjectMapper objectMapper = new ObjectMapper();
        objectMapper.setSerializationInclusion(JsonInclude.Include.NON_NULL);
        String json = objectMapper.writeValueAsString(deviceReportRespDTO);
        byte[] jsonBytes = json.getBytes(StandardCharsets.UTF_8);
        return ResponseEntity
                .ok()
                .contentType(MediaType.APPLICATION_JSON)
                .contentLength(jsonBytes.length)
                .body(json);
    }
}
