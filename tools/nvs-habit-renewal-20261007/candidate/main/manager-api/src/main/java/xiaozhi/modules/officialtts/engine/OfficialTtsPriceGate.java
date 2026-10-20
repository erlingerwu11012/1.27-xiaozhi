package xiaozhi.modules.officialtts.engine;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * Sale price must match operation + model + region + unit + version.
 * Encoding in official_tts_price.version: {@code model|region|versionId}.
 */
public final class OfficialTtsPriceGate {
    public static final String MODEL = "qwen-audio-3.0-tts-plus";
    public static final String REGION = "cn-beijing";

    public static final class Row {
        public final String priceKind;
        public final String operation;
        public final String version;
        public final String unit;
        public final BigDecimal amount;
        public final String status;

        public Row(String priceKind, String operation, String version, String unit, BigDecimal amount, String status) {
            this.priceKind = priceKind;
            this.operation = operation;
            this.version = version;
            this.unit = unit;
            this.amount = amount;
            this.status = status;
        }
    }

    public static final class Frozen {
        public final String operation;
        public final String model;
        public final String region;
        public final String unit;
        public final String version;
        public final BigDecimal amount;

        public Frozen(String operation, String model, String region, String unit, String version, BigDecimal amount) {
            this.operation = operation;
            this.model = model;
            this.region = region;
            this.unit = unit;
            this.version = version;
            this.amount = amount;
        }
    }

    private final List<Row> rows;

    public OfficialTtsPriceGate(List<Row> rows) {
        this.rows = rows == null ? List.of() : new ArrayList<>(rows);
    }

    public Frozen require(String operation, String model, String region, String unit) {
        for (Row row : rows) {
            if (!"sale_points".equals(row.priceKind) || !"active".equals(row.status)) {
                continue;
            }
            if (!Objects.equals(operation, row.operation) || !Objects.equals(unit, row.unit)) {
                continue;
            }
            if (row.amount == null || row.amount.signum() < 0) {
                continue;
            }
            String[] parts = row.version == null ? new String[0] : row.version.split("\\|", -1);
            if (parts.length != 3) {
                continue;
            }
            if (model.equals(parts[0]) && region.equals(parts[1])) {
                return new Frozen(operation, model, region, unit, row.version, row.amount);
            }
        }
        throw new IllegalStateException("pricing_pending:" + operation + ":" + model + ":" + region + ":" + unit);
    }
}
