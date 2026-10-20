"""Package actual firmware stores and the isolated host-test dependencies."""
import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ["settings", "habit_manager", "note_manager", "alarm_manager", "identity_manager", "behavior_logger", "person_directory"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--idf", type=Path, default=Path("E:/Espressif/frameworks/esp-idf-v5.5.4"))
    args = parser.parse_args()
    destination = ROOT / "tmp/bailian-memory-product/firmware-host.tar.gz"
    with tarfile.open(destination, "w:gz") as archive:
        for source in SOURCES:
            for suffix in (".cc", ".h"):
                path = ROOT / "main" / (source + suffix)
                archive.add(path, arcname="main/" + path.name)
        for name in ("person_turn.h", "weekly_schedule.h", "user_context.h", "reminder_coordinator.h"):
            archive.add(ROOT / "main" / name, arcname="main/" + name)
        for path in (ROOT / "tools/host_stubs/face_config").glob("*.h"):
            archive.add(path, arcname="stubs/" + path.name)
        for path in (ROOT / "tools/bailian-memory-product/firmware_host").glob("*"):
            if path.is_file():
                archive.add(path, arcname="stubs/" + path.name)
        for name in ("cJSON.c", "cJSON.h"):
            archive.add(args.idf / "components/json/cJSON" / name, arcname="cjson/" + name)
    print(destination)

if __name__ == "__main__":
    main()
