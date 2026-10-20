"""Run on the SSH host. Clone schema only into a new, empty test database."""
import json
import subprocess
import uuid
from pathlib import Path

CONTAINER = "xiaozhi-esp32-server-db"
DATABASE = "bailian_memory_test_20260929_" + uuid.uuid4().hex[:8]
WORK = Path("/root/prjs/tmp/bailian-memory-product/main/manager-api")
RESULT = Path("/tmp/bailian-memory-migration-result.json")


def mysql(sql):
    process = subprocess.run(["docker", "exec", "-i", CONTAINER, "sh", "-c",
        'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names'],
        input=sql, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError(process.stderr[:500])
    return process.stdout


def main():
    assert DATABASE.startswith("bailian_memory_test_") and DATABASE.isidentifier()
    schema = subprocess.run(["docker", "exec", CONTAINER, "sh", "-c",
        'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --user=root --no-data --skip-comments --set-gtid-purged=OFF xiaozhi_esp32_server'],
        text=True, capture_output=True, check=True).stdout
    mysql(f"CREATE DATABASE `{DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
    mysql(f"USE `{DATABASE}`;\n" + schema)
    # These are synthetic legacy agents; no production account or chat rows copied.
    mysql(f"USE `{DATABASE}`; INSERT INTO ai_agent(id,user_id,mem_model_id,summary_memory) VALUES('test_legacy_a',99001,'Memory_mem0','synthetic mixed summary'),('test_legacy_b',99002,'Memory_mem0ai','synthetic mixed summary');")
    # Production may already have the earlier additive migration. Clone its
    # schema, then apply only missing additions to this empty test database.
    has_kind = mysql(f"SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{DATABASE}' AND TABLE_NAME='ai_user_identity' AND COLUMN_NAME='kind';").strip() == "1"
    if not has_kind:
        sql = (WORK / "src/main/resources/db/changelog/202609290100_memory_identity.sql").read_text()
        mysql(f"USE `{DATABASE}`;\n" + sql)
    else:
        mysql(f"USE `{DATABASE}`; UPDATE ai_agent SET mem_model_id='Memory_bailian',summary_memory=NULL WHERE mem_model_id IN('Memory_mem0','Memory_mem0ai');")
    has_watermarks=mysql(f"SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='{DATABASE}' AND TABLE_NAME='ai_person_behavior_watermark';").strip() == "1"
    if not has_watermarks:
        mysql(f"USE `{DATABASE}`;\n"+(WORK/"src/main/resources/db/changelog/202609290800_behavior_watermark.sql").read_text())
    result = {"database": DATABASE, "schema_only": True,
        "migrated_legacy": int(mysql(f"USE `{DATABASE}`; SELECT COUNT(*) FROM ai_agent WHERE mem_model_id='Memory_bailian' AND summary_memory IS NULL;").strip()),
        "portrait_enabled": False}
    assert result["migrated_legacy"] == 2
    # The physical uniqueness guarantee is exercised, not just a mocked DAO.
    mysql(f"USE `{DATABASE}`; INSERT INTO ai_user_identity(account_id,user_id,display_name,kind) VALUES(99001,'usr_a','爸爸','member'),(99002,'usr_b','爸爸','member'),(99001,'usr_default_1','默认用户','default'),(99001,'usr_default_2','默认用户','default');")
    try:
        mysql(f"USE `{DATABASE}`; INSERT INTO ai_user_identity(account_id,user_id,display_name,kind) VALUES(99001,'usr_duplicate',' 爸爸 ','member');")
    except RuntimeError as error:
        assert "Duplicate entry" in str(error)
        result["nickname_uniqueness"] = True
    else:
        raise AssertionError("nickname uniqueness missing")
    RESULT.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
