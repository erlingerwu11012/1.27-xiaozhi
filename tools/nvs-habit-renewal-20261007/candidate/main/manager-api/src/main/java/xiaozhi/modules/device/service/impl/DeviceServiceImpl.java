package xiaozhi.modules.device.service.impl;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TimeZone;
import java.util.UUID;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.apache.commons.lang3.StringUtils;
import org.springframework.aop.framework.AopContext;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;

import cn.hutool.core.util.RandomUtil;
import jakarta.servlet.http.HttpServletRequest;
import lombok.AllArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.page.PageData;
import xiaozhi.common.redis.RedisKeys;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.common.service.impl.BaseServiceImpl;
import xiaozhi.common.user.UserDetail;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.common.utils.DateUtils;
import xiaozhi.modules.device.dao.DeviceDao;
import xiaozhi.modules.device.dto.DeviceManualAddDTO;
import xiaozhi.modules.device.dto.DevicePageUserDTO;
import xiaozhi.modules.device.dto.DeviceReportReqDTO;
import xiaozhi.modules.device.dto.DeviceReportRespDTO;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.entity.OtaEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.device.service.DeviceWsAuthService;
import xiaozhi.modules.device.service.DeviceWsTokenService;
import xiaozhi.modules.device.service.OtaService;
import xiaozhi.modules.device.service.impl.DeviceWsRevokeNotifyService;
import xiaozhi.modules.device.util.DeviceBootstrapCrypto;
import xiaozhi.modules.device.util.MacAddressUtils;
import xiaozhi.modules.device.vo.DeviceUnbindResultVO;
import xiaozhi.modules.device.vo.DeviceWsAuthStateVO;
import xiaozhi.modules.device.vo.UserShowDeviceListVO;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.sys.service.SysParamsService;
import xiaozhi.modules.sys.service.SysUserUtilService;

@Slf4j
@Service
@AllArgsConstructor
public class DeviceServiceImpl extends BaseServiceImpl<DeviceDao, DeviceEntity> implements DeviceService {

    private final DeviceDao deviceDao;
    private final SysUserUtilService sysUserUtilService;
    private final SysParamsService sysParamsService;
    private final RedisUtils redisUtils;
    private final OtaService otaService;
    private final DeviceWsTokenService deviceWsTokenService;
    private final DeviceWsAuthService deviceWsAuthService;
    private final DeviceWsRevokeNotifyService deviceWsRevokeNotifyService;

    /** 用户配对 6 位码 Redis TTL：与历史一致 24h（低熵，仅控制台绑定）。 */
    private static final long ACTIVATION_PAIRING_TTL_SEC = RedisUtils.DEFAULT_EXPIRE;
    /** 高熵 bootstrap 兑换 TTL：15 分钟。 */
    private static final long BOOTSTRAP_REDEEM_TTL_SEC = 15 * 60L;
    /** 单设备兑换/鉴权失败限流窗口与上限。 */
    private static final long BOOTSTRAP_FAIL_WINDOW_SEC = 15 * 60L;
    private static final long BOOTSTRAP_FAIL_MAX = 20L;

    @Async
    public void updateDeviceConnectionInfo(String agentId, String deviceId, String appVersion) {
        try {
            DeviceEntity device = new DeviceEntity();
            device.setId(deviceId);
            device.setLastConnectedAt(new Date());
            if (StringUtils.isNotBlank(appVersion)) {
                device.setAppVersion(appVersion);
            }
            deviceDao.updateById(device);
            if (StringUtils.isNotBlank(agentId)) {
                redisUtils.set(RedisKeys.getAgentDeviceLastConnectedAtById(agentId), new Date());
            }
        } catch (Exception e) {
            log.error("异步更新设备连接信息失败", e);
        }
    }

    @Override
    public Boolean deviceActivation(String agentId, String activationCode) {
        if (StringUtils.isBlank(activationCode)) {
            throw new RenException(ErrorCode.ACTIVATION_CODE_EMPTY);
        }
        String deviceKey = "ota:activation:code:" + activationCode;
        Object cacheDeviceId = redisUtils.get(deviceKey);
        if (cacheDeviceId == null) {
            throw new RenException(ErrorCode.ACTIVATION_CODE_ERROR);
        }
        String deviceId = (String) cacheDeviceId;
        String safeDeviceId = deviceId.replace(":", "_").toLowerCase();
        String cacheDeviceKey = String.format("ota:activation:data:%s", safeDeviceId);
        Map<String, Object> cacheMap = (Map<String, Object>) redisUtils.get(cacheDeviceKey);
        if (cacheMap == null) {
            throw new RenException(ErrorCode.ACTIVATION_CODE_ERROR);
        }
        String cachedCode = (String) cacheMap.get("activation_code");
        if (!activationCode.equals(cachedCode)) {
            throw new RenException(ErrorCode.ACTIVATION_CODE_ERROR);
        }
        // 检查设备有没有被激活
        if (selectById(deviceId) != null) {
            throw new RenException(ErrorCode.DEVICE_ALREADY_ACTIVATED);
        }

        String macAddress = (String) cacheMap.get("mac_address");
        String board = (String) cacheMap.get("board");
        String appVersion = (String) cacheMap.get("app_version");
        UserDetail user = SecurityUser.getUser();
        if (user.getId() == null) {
            throw new RenException(ErrorCode.USER_NOT_LOGIN);
        }

        Date currentTime = new Date();
        DeviceEntity deviceEntity = new DeviceEntity();
        deviceEntity.setId(deviceId);
        deviceEntity.setBoard(board);
        deviceEntity.setAgentId(agentId);
        deviceEntity.setAppVersion(appVersion);
        deviceEntity.setMacAddress(macAddress);
        deviceEntity.setUserId(user.getId());
        deviceEntity.setCreator(user.getId());
        deviceEntity.setAutoUpdate(1);
        deviceEntity.setCreateDate(currentTime);
        deviceEntity.setUpdater(user.getId());
        deviceEntity.setUpdateDate(currentTime);
        deviceEntity.setLastConnectedAt(currentTime);
        deviceDao.insert(deviceEntity);

        // 清理redis缓存
        redisUtils.delete(cacheDeviceKey);
        redisUtils.delete(deviceKey);

        // 添加：清除智能体设备数量缓存
        redisUtils.delete(RedisKeys.getAgentDeviceCountById(agentId));

        // WSS auth：新绑定 → active + 新 bootstrap；高熵 bootstrap_code 用于设备端一次性兑换
        try {
            String bootstrapPlain = deviceWsAuthService.provisionNewBootstrap(macAddress);
            String bootstrapCode = cacheMap.get("bootstrap_code") == null
                    ? null
                    : String.valueOf(cacheMap.get("bootstrap_code"));
            if (StringUtils.isBlank(bootstrapCode)) {
                // 兼容旧缓存无 bootstrap_code：绑定瞬间生成高熵兑换码
                bootstrapCode = DeviceBootstrapCrypto.generatePlaintext();
            }
            storeBootstrapRedeem(macAddress, bootstrapPlain, bootstrapCode);
        } catch (Exception e) {
            log.error("初始化设备 WSS auth/bootstrap 失败 device_id_set={}", macAddress != null);
            throw e;
        }

        return true;
    }

    @Override
    public DeviceReportRespDTO checkDeviceActive(String macAddress, String clientId,
            DeviceReportReqDTO deviceReport, String authorization, String activationCode) {
        DeviceReportRespDTO response = new DeviceReportRespDTO();
        response.setServer_time(buildServerTime());

        String canonicalMac = MacAddressUtils.toCanonical(macAddress);
        DeviceEntity deviceById = canonicalMac == null ? null : getDeviceByMacAddress(canonicalMac);

        String appVersion = deviceReport != null
                && deviceReport.getApplication() != null
                && deviceReport.getApplication().getVersion() != null
                        ? deviceReport.getApplication().getVersion()
                        : "0.0.0";

        if (deviceById == null) {
            DeviceReportRespDTO.Firmware firmware = new DeviceReportRespDTO.Firmware();
            firmware.setVersion(appVersion);
            firmware.setUrl(Constant.INVALID_FIRMWARE_URL);
            response.setFirmware(firmware);
            response.setActivation(buildActivation(canonicalMac != null ? canonicalMac : macAddress, deviceReport));
            attachWebsocketUrlOnly(response);
            return response;
        }

        // 已绑定：固件检查始终可用；token 仅在合法 device_auth_key / 高熵 bootstrap 兑换后签发
        if (deviceById.getAutoUpdate() != null && deviceById.getAutoUpdate() != 0) {
            String type = deviceReport.getBoard() == null ? null : deviceReport.getBoard().getType();
            DeviceReportRespDTO.Firmware firmware = buildFirmwareInfo(type, appVersion);
            if (firmware != null) {
                response.setFirmware(firmware);
            }
        }

        if (isBootstrapRateLimited(canonicalMac)) {
            attachWebsocketUrlOnly(response);
            return response;
        }

        String presented = extractBearer(authorization);
        String deliveredAuthKey = null;
        boolean authorized = false;

        // 路径 A：高熵 bootstrap_code 一次性兑换（X-Activation-Code）
        if (StringUtils.isNotBlank(activationCode)) {
            deliveredAuthKey = redeemBootstrap(canonicalMac, activationCode.trim());
            if (deliveredAuthKey != null) {
                authorized = true;
            } else {
                recordBootstrapFailure(canonicalMac);
            }
        }

        // 路径 B：Authorization Bearer = 设备 device_auth_key（唯一允许的 refresh 凭证）
        // 禁止用 WSS token 兑换新 token / auth_key
        if (!authorized && StringUtils.isNotBlank(presented)) {
            if (looksLikeWsToken(presented)) {
                recordBootstrapFailure(canonicalMac);
            } else if (deviceWsAuthService.verifyBootstrapKey(canonicalMac, presented)) {
                authorized = true;
            } else {
                recordBootstrapFailure(canonicalMac);
            }
        }

        if (!authorized) {
            // 已绑定旧设备迁移：active 且尚无 device_auth_key → 仅下发 bootstrap_code，不发 token/auth_key
            if (needsLegacyBootstrapMigration(canonicalMac)) {
                String migrationCode = ensureMigrationBootstrapRedeem(canonicalMac);
                if (StringUtils.isNotBlank(migrationCode)) {
                    DeviceReportRespDTO.Activation activation = new DeviceReportRespDTO.Activation();
                    activation.setBootstrap_code(migrationCode);
                    response.setActivation(activation);
                }
                attachWebsocketUrlOnly(response);
                touchConnectionInfo(deviceById, appVersion);
                return response;
            }
            attachWebsocketUrlOnly(response);
            touchConnectionInfo(deviceById, appVersion);
            return response;
        }

        String token;
        try {
            long credVer = deviceWsAuthService.ensureActiveForIssue(canonicalMac);
            token = deviceWsTokenService.issueToken(canonicalMac, clientId, credVer);
        } catch (Exception e) {
            log.error("为设备签发 WSS token 失败，device_id_set={}（不输出密钥/token）", canonicalMac != null);
            attachWebsocketUrlOnly(response);
            return response;
        }

        DeviceReportRespDTO.Websocket websocket = new DeviceReportRespDTO.Websocket();
        websocket.setUrl(resolveWebsocketUrl());
        websocket.setToken(token);
        websocket.setVersion(2);
        if (deliveredAuthKey != null) {
            websocket.setAuth_key(deliveredAuthKey);
        }
        response.setWebsocket(websocket);

        String mqttUdpConfig = sysParamsService.getValue(Constant.SERVER_MQTT_GATEWAY, false);
        if (mqttUdpConfig != null && !"null".equals(mqttUdpConfig) && !mqttUdpConfig.isEmpty()) {
            try {
                String groupId = deviceById.getBoard() != null ? deviceById.getBoard() : "GID_default";
                DeviceReportRespDTO.MQTT mqtt = buildMqttConfig(canonicalMac, groupId);
                if (mqtt != null) {
                    mqtt.setEndpoint(mqttUdpConfig);
                    response.setMqtt(mqtt);
                }
            } catch (Exception e) {
                log.error("生成MQTT配置失败: {}", e.getMessage());
            }
        }

        touchConnectionInfo(deviceById, appVersion);

        return response;
    }

    private void touchConnectionInfo(DeviceEntity deviceById, String appVersion) {
        try {
            ((DeviceServiceImpl) AopContext.currentProxy()).updateDeviceConnectionInfo(
                    deviceById.getAgentId(), deviceById.getId(), appVersion);
        } catch (IllegalStateException e) {
            // 单测无 AopContext 时降级直调（@Async 自调用本就不代理）
            updateDeviceConnectionInfo(deviceById.getAgentId(), deviceById.getId(), appVersion);
        }
    }

    private static boolean looksLikeWsToken(String presented) {
        if (presented == null) {
            return false;
        }
        // v2: v2.sig.iat.exp.ver 或 v1: sig.iat.exp
        String[] parts = presented.split("\\.");
        if (parts.length == 5 && "v2".equals(parts[0])) {
            return true;
        }
        if (parts.length == 3) {
            try {
                Long.parseLong(parts[1]);
                Long.parseLong(parts[2]);
                return true;
            } catch (NumberFormatException e) {
                return false;
            }
        }
        return false;
    }

    private void attachWebsocketUrlOnly(DeviceReportRespDTO response) {
        DeviceReportRespDTO.Websocket websocket = new DeviceReportRespDTO.Websocket();
        websocket.setUrl(resolveWebsocketUrl());
        websocket.setVersion(2);
        response.setWebsocket(websocket);
    }

    private String resolveWebsocketUrl() {
        String wsUrl = sysParamsService.getValue(Constant.SERVER_WEBSOCKET, true);
        if (StringUtils.isBlank(wsUrl) || "null".equals(wsUrl)) {
            log.error("WebSocket地址未配置，请登录智控台，在参数管理找到【server.websocket】配置");
            return "ws://xiaozhi.server.com:8000/xiaozhi/v1/";
        }
        String[] wsUrls = wsUrl.split(";");
        if (wsUrls.length == 1) {
            return wsUrls[0].trim();
        }
        int idx = java.util.concurrent.ThreadLocalRandom.current().nextInt(wsUrls.length);
        return wsUrls[idx].trim();
    }

    private static String extractBearer(String authorization) {
        if (StringUtils.isBlank(authorization)) {
            return null;
        }
        String v = authorization.trim();
        if (v.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return v.substring(7).trim();
        }
        return v;
    }

    private static String bootstrapRedeemKey(String macOrCanonical) {
        String normalized = MacAddressUtils.toTokenDeviceId(macOrCanonical);
        if (normalized == null) {
            normalized = MacAddressUtils.toTokenDeviceId(MacAddressUtils.toCanonical(macOrCanonical));
        }
        return "ota:bootstrap:redeem:" + normalized;
    }

    private static String bootstrapFailKey(String macOrCanonical) {
        String normalized = MacAddressUtils.toTokenDeviceId(macOrCanonical);
        if (normalized == null) {
            normalized = MacAddressUtils.toTokenDeviceId(MacAddressUtils.toCanonical(macOrCanonical));
        }
        return "ota:bootstrap:fail:" + normalized;
    }

    private boolean isBootstrapRateLimited(String canonicalMac) {
        Object v = redisUtils.get(bootstrapFailKey(canonicalMac));
        if (v == null) {
            return false;
        }
        try {
            return Long.parseLong(String.valueOf(v)) >= BOOTSTRAP_FAIL_MAX;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    private void recordBootstrapFailure(String canonicalMac) {
        String key = bootstrapFailKey(canonicalMac);
        // increment(key, expireSeconds)：+1 并刷新窗口 TTL
        redisUtils.increment(key, BOOTSTRAP_FAIL_WINDOW_SEC);
    }

    private void storeBootstrapRedeem(String macAddress, String bootstrapPlain, String bootstrapCode) {
        String normalized = MacAddressUtils.toTokenDeviceId(macAddress);
        if (normalized == null) {
            normalized = MacAddressUtils.toTokenDeviceId(MacAddressUtils.toCanonical(macAddress));
        }
        String key = bootstrapRedeemKey(macAddress);
        Map<String, Object> map = new HashMap<>();
        map.put("device_id", normalized);
        map.put("bootstrap_code", bootstrapCode);
        map.put("auth_key", bootstrapPlain);
        redisUtils.set(key, map, BOOTSTRAP_REDEEM_TTL_SEC);
    }

    /**
     * 已绑定且 active、但尚未配置 device_auth_key（bootstrap_key_hash 为空）→ 需迁移。
     */
    private boolean needsLegacyBootstrapMigration(String canonicalMac) {
        DeviceWsAuthStateVO state = deviceWsAuthService.getState(canonicalMac);
        if (state == null) {
            // 历史绑定设备可能从未写入 ai_device_ws_auth
            return true;
        }
        if (!"active".equals(state.getStatus())) {
            return false;
        }
        return !Boolean.TRUE.equals(state.getBootstrapConfigured());
    }

    /**
     * 为旧设备准备一次性 migration redeem；若已有未核销 redeem 则复用同一 bootstrap_code。
     * 不在此响应中返回 auth_key / token。
     */
    @SuppressWarnings("unchecked")
    private String ensureMigrationBootstrapRedeem(String canonicalMac) {
        String key = bootstrapRedeemKey(canonicalMac);
        Object raw = redisUtils.get(key);
        if (raw instanceof Map<?, ?> existing) {
            Object bc = existing.get("bootstrap_code");
            if (bc == null) {
                bc = existing.get("activation_code");
            }
            if (bc != null && StringUtils.isNotBlank(String.valueOf(bc))) {
                return String.valueOf(bc);
            }
        }
        String authKeyPlain = deviceWsAuthService.provisionNewBootstrap(canonicalMac);
        String bootstrapCode = DeviceBootstrapCrypto.generatePlaintext();
        storeBootstrapRedeem(canonicalMac, authKeyPlain, bootstrapCode);
        log.info("[ws_auth] legacy_migration_bootstrap_issued device_id_set=true");
        return bootstrapCode;
    }

    /**
     * 原子兑换：锁 + getAndDelete；校验 device_id 绑定与高熵 bootstrap_code；重放失败。
     * 不记录 code / auth_key 明文。
     */
    @SuppressWarnings("unchecked")
    private String redeemBootstrap(String canonicalMac, String bootstrapCode) {
        String normalized = MacAddressUtils.toTokenDeviceId(canonicalMac);
        if (normalized == null || StringUtils.isBlank(bootstrapCode)) {
            return null;
        }
        String key = bootstrapRedeemKey(canonicalMac);
        String lockKey = key + ":lock";
        if (!redisUtils.setIfAbsent(lockKey, "1", 5L)) {
            return null;
        }
        try {
            Object raw = redisUtils.getAndDelete(key);
            if (!(raw instanceof Map)) {
                return null;
            }
            Map<String, Object> map = (Map<String, Object>) raw;
            String boundDevice = map.get("device_id") == null ? null : String.valueOf(map.get("device_id"));
            String cachedCode = map.get("bootstrap_code") == null ? null : String.valueOf(map.get("bootstrap_code"));
            // 兼容旧字段名
            if (cachedCode == null && map.get("activation_code") != null) {
                cachedCode = String.valueOf(map.get("activation_code"));
            }
            String authKey = map.get("auth_key") == null ? null : String.valueOf(map.get("auth_key"));
            if (StringUtils.isBlank(boundDevice) || StringUtils.isBlank(cachedCode) || StringUtils.isBlank(authKey)) {
                return null;
            }
            if (!normalized.equals(boundDevice)) {
                return null;
            }
            byte[] a = cachedCode.getBytes(StandardCharsets.UTF_8);
            byte[] b = bootstrapCode.getBytes(StandardCharsets.UTF_8);
            if (!java.security.MessageDigest.isEqual(a, b)) {
                return null;
            }
            return authKey;
        } finally {
            redisUtils.delete(lockKey);
        }
    }

    @Override
    public List<DeviceEntity> getUserDevices(Long userId, String agentId) {
        QueryWrapper<DeviceEntity> wrapper = new QueryWrapper<>();
        wrapper.eq("user_id", userId);
        wrapper.eq("agent_id", agentId);
        return baseDao.selectList(wrapper);
    }

    @Override
    public DeviceUnbindResultVO unbindDevice(Long userId, String deviceId) {
        DeviceUnbindResultVO vo = new DeviceUnbindResultVO();
        DeviceEntity device = baseDao.selectById(deviceId);
        if (device == null) {
            vo.setAuthStatePersisted(false);
            vo.setRevokeStatus("noop");
            vo.setSyncClosed(false);
            return vo;
        }
        UnbindTxResult tx;
        try {
            tx = ((DeviceServiceImpl) AopContext.currentProxy())
                    .unbindDeviceTransactional(userId, device);
        } catch (IllegalStateException e) {
            tx = unbindDeviceTransactional(userId, device);
        }
        vo.setAuthStatePersisted(true);
        vo.setCredentialVersion(tx.credentialVersion());
        boolean syncOk = false;
        String revokeStatus = "pending";
        try {
            syncOk = deviceWsRevokeNotifyService.tryNotify(
                    tx.normalizedDeviceId(), tx.credentialVersion(), "unbound");
            revokeStatus = syncOk ? "sync_closed" : "pending";
        } catch (Exception e) {
            log.warn("[ws_revoke] unbind notify err_type={}", e.getClass().getSimpleName());
            syncOk = false;
            revokeStatus = "failed";
        }
        vo.setSyncClosed(syncOk);
        vo.setRevokeStatus(revokeStatus);
        log.info("[ws_unbind] auth_persisted=true revoke_status={} sync_closed={}",
                vo.getRevokeStatus(), syncOk);
        return vo;
    }

    @org.springframework.transaction.annotation.Transactional(rollbackFor = Exception.class)
    public UnbindTxResult unbindDeviceTransactional(Long userId, DeviceEntity device) {
        if (StringUtils.isNotBlank(device.getAgentId())) {
            redisUtils.delete(RedisKeys.getAgentDeviceCountById(device.getAgentId()));
        }
        String macForAuth = device.getMacAddress() != null ? device.getMacAddress() : device.getId();
        String normalized = MacAddressUtils.toTokenDeviceId(macForAuth);
        if (normalized == null) {
            normalized = MacAddressUtils.toTokenDeviceId(MacAddressUtils.toCanonical(macForAuth));
        }
        long ver = 0L;
        try {
            ver = deviceWsAuthService.markUnbound(macForAuth);
        } catch (IllegalArgumentException e) {
            log.warn("[ws_auth] unbind markUnbound skipped reason=invalid_mac");
        }
        UpdateWrapper<DeviceEntity> wrapper = new UpdateWrapper<>();
        wrapper.eq("user_id", userId);
        wrapper.eq("id", device.getId());
        baseDao.delete(wrapper);
        return new UnbindTxResult(normalized, ver);
    }

    public record UnbindTxResult(String normalizedDeviceId, long credentialVersion) {
    }

    @Override
    public void deleteByUserId(Long userId) {
        UpdateWrapper<DeviceEntity> wrapper = new UpdateWrapper<>();
        wrapper.eq("user_id", userId);
        baseDao.delete(wrapper);
    }

    @Override
    public Long selectCountByUserId(Long userId) {
        UpdateWrapper<DeviceEntity> wrapper = new UpdateWrapper<>();
        wrapper.eq("user_id", userId);
        return baseDao.selectCount(wrapper);
    }

    @Override
    public void deleteByAgentId(String agentId) {
        UpdateWrapper<DeviceEntity> wrapper = new UpdateWrapper<>();
        wrapper.eq("agent_id", agentId);
        baseDao.delete(wrapper);
    }

    @Override
    public PageData<UserShowDeviceListVO> page(DevicePageUserDTO dto) {
        Map<String, Object> params = new HashMap<String, Object>();
        params.put(Constant.PAGE, dto.getPage());
        params.put(Constant.LIMIT, dto.getLimit());
        IPage<DeviceEntity> page = baseDao.selectPage(
                getPage(params, "mac_address", true),
                // 定义查询条件
                new QueryWrapper<DeviceEntity>()
                        // 必须设备关键词查找
                        .like(StringUtils.isNotBlank(dto.getKeywords()), "alias", dto.getKeywords()));
        // 循环处理page获取回来的数据，返回需要的字段
        List<UserShowDeviceListVO> list = page.getRecords().stream().map(device -> {
            UserShowDeviceListVO vo = ConvertUtils.sourceToTarget(device, UserShowDeviceListVO.class);
            // 把最后修改的时间，改为简短描述的时间
            vo.setRecentChatTime(DateUtils.getShortTime(device.getUpdateDate()));
            sysUserUtilService.assignUsername(device.getUserId(),
                    vo::setBindUserName);
            vo.setDeviceType(device.getBoard());
            return vo;
        }).toList();
        // 计算页数
        return new PageData<>(list, page.getTotal());
    }

    @Override
    public DeviceEntity getDeviceByMacAddress(String macAddress) {
        // 统一规范化 MAC 后按数据库规范格式查询，支持大小写、带/不带分隔符
        String canonical = MacAddressUtils.toCanonical(macAddress);
        if (canonical == null) {
            return null;
        }
        QueryWrapper<DeviceEntity> wrapper = new QueryWrapper<>();
        wrapper.eq("mac_address", canonical);
        return baseDao.selectOne(wrapper);
    }

    private DeviceReportRespDTO.ServerTime buildServerTime() {
        DeviceReportRespDTO.ServerTime serverTime = new DeviceReportRespDTO.ServerTime();
        TimeZone tz = TimeZone.getDefault();
        serverTime.setTimestamp(Instant.now().toEpochMilli());
        serverTime.setTimeZone(tz.getID());
        serverTime.setTimezone_offset(tz.getOffset(System.currentTimeMillis()) / (60 * 1000));
        return serverTime;
    }

    @Override
    public String geCodeByDeviceId(String deviceId) {
        String dataKey = getDeviceCacheKey(deviceId);

        Map<String, Object> cacheMap = (Map<String, Object>) redisUtils.get(dataKey);
        if (cacheMap != null && cacheMap.containsKey("activation_code")) {
            String cachedCode = (String) cacheMap.get("activation_code");
            return cachedCode;
        }
        return null;
    }

    @Override
    public Date getLatestLastConnectionTime(String agentId) {
        // 查询是否有缓存时间，有则返回
        Date cachedDate = (Date) redisUtils.get(RedisKeys.getAgentDeviceLastConnectedAtById(agentId));
        if (cachedDate != null) {
            return cachedDate;
        }
        Date maxDate = deviceDao.getAllLastConnectedAtByAgentId(agentId);
        if (maxDate != null) {
            redisUtils.set(RedisKeys.getAgentDeviceLastConnectedAtById(agentId), maxDate);
        }
        return maxDate;
    }

    private String getDeviceCacheKey(String deviceId) {
        String safeDeviceId = deviceId.replace(":", "_").toLowerCase();
        String dataKey = String.format("ota:activation:data:%s", safeDeviceId);
        return dataKey;
    }

    public DeviceReportRespDTO.Activation buildActivation(String deviceId, DeviceReportReqDTO deviceReport) {
        DeviceReportRespDTO.Activation code = new DeviceReportRespDTO.Activation();

        String cachedCode = geCodeByDeviceId(deviceId);
        String dataKey = getDeviceCacheKey(deviceId);

        if (StringUtils.isNotBlank(cachedCode)) {
            code.setCode(cachedCode);
            String frontedUrl = sysParamsService.getValue(Constant.SERVER_FRONTED_URL, true);
            code.setMessage(frontedUrl + "\n" + cachedCode);
            code.setChallenge(deviceId);
            Object raw = redisUtils.get(dataKey);
            if (raw instanceof Map<?, ?> cacheMap) {
                Object bc = cacheMap.get("bootstrap_code");
                if (bc != null) {
                    code.setBootstrap_code(String.valueOf(bc));
                }
            }
        } else {
            // 用户配对：6 位十进制 ≈ 19.9 bit（低熵）；仅控制台绑定，配严格设备绑定 + 短码反查
            String newCode = RandomUtil.randomNumbers(6);
            // 设备兑换：256-bit 高熵凭证
            String bootstrapCode = DeviceBootstrapCrypto.generatePlaintext();
            code.setCode(newCode);
            code.setBootstrap_code(bootstrapCode);
            String frontedUrl = sysParamsService.getValue(Constant.SERVER_FRONTED_URL, true);
            code.setMessage(frontedUrl + "\n" + newCode);
            code.setChallenge(deviceId);

            Map<String, Object> dataMap = new HashMap<>();
            dataMap.put("id", deviceId);
            dataMap.put("mac_address", deviceId);
            dataMap.put("board", (deviceReport.getBoard() != null && deviceReport.getBoard().getType() != null)
                    ? deviceReport.getBoard().getType()
                    : (deviceReport.getChipModelName() != null ? deviceReport.getChipModelName() : "unknown"));
            dataMap.put("app_version", (deviceReport.getApplication() != null)
                    ? deviceReport.getApplication().getVersion()
                    : null);
            dataMap.put("deviceId", deviceId);
            dataMap.put("activation_code", newCode);
            dataMap.put("bootstrap_code", bootstrapCode);

            redisUtils.set(dataKey, dataMap, ACTIVATION_PAIRING_TTL_SEC);
            String codeKey = "ota:activation:code:" + newCode;
            redisUtils.set(codeKey, deviceId, ACTIVATION_PAIRING_TTL_SEC);
        }
        return code;
    }

    private DeviceReportRespDTO.Firmware buildFirmwareInfo(String type, String currentVersion) {
        if (StringUtils.isBlank(type)) {
            return null;
        }
        if (StringUtils.isBlank(currentVersion)) {
            currentVersion = "0.0.0";
        }

        OtaEntity ota = otaService.getLatestOta(type);
        // 无该机型固件，或不存在更高版本：省略 firmware（不返回伪下载地址）
        if (ota == null) {
            return null;
        }
        if (compareVersions(ota.getVersion(), currentVersion) <= 0) {
            return null;
        }

        String otaUrl = sysParamsService.getValue(Constant.SERVER_OTA, true);
        if (StringUtils.isBlank(otaUrl) || otaUrl.equals("null")) {
            log.error("OTA地址未配置，请登录智控台，在参数管理找到【server.ota】配置");
            // 尝试从请求中获取
            HttpServletRequest request = ((ServletRequestAttributes) RequestContextHolder
                    .getRequestAttributes())
                    .getRequest();
            otaUrl = request.getRequestURL().toString();
        }
        // 将URL中的/ota/替换为/otaMag/download/
        String uuid = UUID.randomUUID().toString();
        redisUtils.set(RedisKeys.getOtaIdKey(uuid), ota.getId());
        String downloadUrl = otaUrl.replace("/ota/", "/otaMag/download/") + uuid;

        // 真正下发升级时必须是可用 HTTPS 地址，否则不下发
        if (downloadUrl == null || !downloadUrl.startsWith("https://")) {
            log.error("OTA 下载地址非 HTTPS，拒绝下发（type={}）", type);
            return null;
        }

        DeviceReportRespDTO.Firmware firmware = new DeviceReportRespDTO.Firmware();
        firmware.setVersion(ota.getVersion());
        firmware.setUrl(downloadUrl);
        return firmware;
    }

    /**
     * 比较两个版本号
     * 
     * @param version1 版本1
     * @param version2 版本2
     * @return 如果version1 > version2返回1，version1 < version2返回-1，相等返回0
     */
    private static int compareVersions(String version1, String version2) {
        if (version1 == null || version2 == null) {
            return 0;
        }

        String[] v1Parts = version1.split("\\.");
        String[] v2Parts = version2.split("\\.");

        int length = Math.max(v1Parts.length, v2Parts.length);
        for (int i = 0; i < length; i++) {
            int v1 = i < v1Parts.length ? Integer.parseInt(v1Parts[i]) : 0;
            int v2 = i < v2Parts.length ? Integer.parseInt(v2Parts[i]) : 0;

            if (v1 > v2) {
                return 1;
            } else if (v1 < v2) {
                return -1;
            }
        }
        return 0;
    }

    @Override
    public void manualAddDevice(Long userId, DeviceManualAddDTO dto) {
        // 检查mac是否已存在
        QueryWrapper<DeviceEntity> wrapper = new QueryWrapper<>();
        wrapper.eq("mac_address", dto.getMacAddress());
        DeviceEntity exist = baseDao.selectOne(wrapper);
        if (exist != null) {
            throw new RenException(ErrorCode.MAC_ADDRESS_ALREADY_EXISTS);
        }
        Date now = new Date();
        DeviceEntity entity = new DeviceEntity();
        entity.setId(dto.getMacAddress());
        entity.setUserId(userId);
        entity.setAgentId(dto.getAgentId());
        entity.setBoard(dto.getBoard());
        entity.setAppVersion(dto.getAppVersion());
        entity.setMacAddress(dto.getMacAddress());
        entity.setCreateDate(now);
        entity.setUpdateDate(now);
        entity.setLastConnectedAt(now);
        entity.setCreator(userId);
        entity.setUpdater(userId);
        entity.setAutoUpdate(1);
        baseDao.insert(entity);

        // 添加：清除智能体设备数量缓存
        redisUtils.delete(RedisKeys.getAgentDeviceCountById(dto.getAgentId()));

        try {
            String bootstrapPlain = deviceWsAuthService.provisionNewBootstrap(dto.getMacAddress());
            // 手动添加：生成高熵 redeem，不经 6 位码；管理员须把 bootstrap_code 安全交给设备
            String bootstrapCode = DeviceBootstrapCrypto.generatePlaintext();
            storeBootstrapRedeem(dto.getMacAddress(), bootstrapPlain, bootstrapCode);
            log.info("[ws_auth] manual_add bootstrap_provisioned device_id_set=true");
        } catch (Exception e) {
            log.error("手动添加设备后初始化 WSS auth/bootstrap 失败");
            throw e;
        }
    }

    /**
     * 生成MQTT密码签名
     * 
     * @param content   签名内容 (clientId + '|' + username)
     * @param secretKey 密钥
     * @return Base64编码的HMAC-SHA256签名
     */
    private String generatePasswordSignature(String content, String secretKey) throws Exception {
        Mac hmac = Mac.getInstance("HmacSHA256");
        SecretKeySpec keySpec = new SecretKeySpec(secretKey.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
        hmac.init(keySpec);
        byte[] signature = hmac.doFinal(content.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(signature);
    }

    /**
     * 构建MQTT配置信息
     * 
     * @param macAddress MAC地址
     * @param groupId    分组ID
     * @return MQTT配置对象
     */
    private DeviceReportRespDTO.MQTT buildMqttConfig(String macAddress, String groupId)
            throws Exception {
        // 从环境变量或系统参数获取签名密钥
        String signatureKey = sysParamsService.getValue("server.mqtt_signature_key", false);
        if (StringUtils.isBlank(signatureKey)) {
            log.warn("缺少MQTT_SIGNATURE_KEY，跳过MQTT配置生成");
            return null;
        }

        // 构建客户端ID格式：groupId@@@macAddress@@@uuid
        String groupIdSafeStr = groupId.replace(":", "_");
        String deviceIdSafeStr = macAddress.replace(":", "_");
        String mqttClientId = String.format("%s@@@%s@@@%s", groupIdSafeStr, deviceIdSafeStr, deviceIdSafeStr);

        // 构建用户数据（包含IP等信息）
        Map<String, String> userData = new HashMap<>();
        // 尝试获取客户端IP
        try {
            ServletRequestAttributes attributes = (ServletRequestAttributes) RequestContextHolder
                    .getRequestAttributes();
            if (attributes != null) {
                HttpServletRequest request = attributes.getRequest();
                String clientIp = request.getRemoteAddr();
                userData.put("ip", clientIp);
            }
        } catch (Exception e) {
            userData.put("ip", "unknown");
        }

        // 将用户数据编码为Base64 JSON
        String userDataJson = new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(userData);
        String username = Base64.getEncoder().encodeToString(userDataJson.getBytes(StandardCharsets.UTF_8));

        // 生成密码签名
        String password = generatePasswordSignature(mqttClientId + "|" + username, signatureKey);

        // 构建MQTT配置
        DeviceReportRespDTO.MQTT mqtt = new DeviceReportRespDTO.MQTT();
        mqtt.setClient_id(mqttClientId);
        mqtt.setUsername(username);
        mqtt.setPassword(password);
        mqtt.setPublish_topic("device-server");
        mqtt.setSubscribe_topic("devices/p2p/" + deviceIdSafeStr);

        return mqtt;
    }
}
