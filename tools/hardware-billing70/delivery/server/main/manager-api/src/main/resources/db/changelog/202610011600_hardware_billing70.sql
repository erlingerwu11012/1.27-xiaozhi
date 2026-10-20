-- Review-only migration. Apply through a NEW Liquibase changeset after candidate
-- MySQL tests. Do not change pay_package or enable the billing switch yet.
CREATE TABLE one_api.hardware_billing_wallet (
 user_id BIGINT NOT NULL PRIMARY KEY,
 product_account VARCHAR(64) NOT NULL,
 state VARCHAR(24) NOT NULL,
 created_at BIGINT NOT NULL,
 legacy_used_quota BIGINT NOT NULL DEFAULT 0,
 UNIQUE KEY ux_hw_wallet_account(product_account)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE one_api.hardware_billing_lot (
 id VARCHAR(128) NOT NULL PRIMARY KEY,
 user_id BIGINT NOT NULL,
 kind VARCHAR(16) NOT NULL,
 remaining TEXT NOT NULL,
 cny_per_point TEXT NOT NULL,
 paid_cents BIGINT NOT NULL DEFAULT 0,
 granted_points BIGINT NOT NULL DEFAULT 0,
 original_points TEXT NOT NULL,
 created_at BIGINT NOT NULL,
 KEY ix_hw_lot_owner(user_id,created_at),
 CONSTRAINT fk_hw_lot_wallet FOREIGN KEY(user_id) REFERENCES one_api.hardware_billing_wallet(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE one_api.hardware_billing_bill (
 id VARCHAR(128) NOT NULL PRIMARY KEY,
 user_id BIGINT NOT NULL,
 payload_hash CHAR(64) NOT NULL,
 price_json TEXT NOT NULL,
 usage_json TEXT,
 usage_hash CHAR(64),
 settlement_legacy_debit TEXT,
 state VARCHAR(24) NOT NULL,
 cost_cny TEXT,
 sale_cny TEXT,
 allocations TEXT NOT NULL,
 reservation_json TEXT NOT NULL,
 created_at BIGINT NOT NULL,
 settled_at BIGINT NOT NULL DEFAULT 0,
 KEY ix_hw_bill_owner_time(user_id,created_at,id),
 KEY ix_hw_bill_state(state,created_at),
 CONSTRAINT fk_hw_bill_wallet FOREIGN KEY(user_id) REFERENCES one_api.hardware_billing_wallet(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE one_api.hardware_billing_adjustment (
 id VARCHAR(128) NOT NULL PRIMARY KEY,
 bill_id VARCHAR(128) NOT NULL,
 user_id BIGINT NOT NULL,
 kind VARCHAR(24) NOT NULL,
 allocations TEXT NOT NULL,
 created_at BIGINT NOT NULL,
 KEY ix_hw_adjustment_owner(user_id,created_at),
 CONSTRAINT fk_hw_adjustment_bill FOREIGN KEY(bill_id) REFERENCES one_api.hardware_billing_bill(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Rollback keeps these financial tables and all compensation records.
-- Recharge package mutation and migration of legacy balances are separate,
-- gated activation actions, requiring an exact cutover snapshot under lock.
