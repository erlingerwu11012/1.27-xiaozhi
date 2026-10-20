"""Back up and stage the new gateway route only. No credentials are emitted."""
import datetime
import pathlib
import shutil


def main():
    root = pathlib.Path('/root/prjs/one-api-bailian')
    main_file = root / 'cmd/bailian/main.go'
    original = main_file.read_text()
    if 'MemoryRoutes' in original:
        raise SystemExit('Memory entrypoint already changed; inspect before staging again.')
    if original.count('g.Routes(r)\n') != 1:
        raise SystemExit('Route anchor does not match; nothing staged.')
    changed = original.replace('g.Routes(r)\n', 'g.Routes(r)\n\tg.MemoryRoutes(r)\n', 1)
    backup = pathlib.Path('/root/backups') / ('oneapi-memory-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, mode=0o700)
    targets = {
        'main.go': main_file,
        'one-api-bailian': pathlib.Path('/opt/one-api-bailian/one-api-bailian'),
        'gateway.env': pathlib.Path('/etc/one-api-bailian.env'),
        'nginx.conf': pathlib.Path('/etc/nginx/sites-available/api.realecho.cn'),
    }
    for name, source in targets.items():
        shutil.copy2(source, backup / name)
    for name in ['memory.go', 'memory_test.go']:
        source = pathlib.Path('/tmp/oneapi-memory-stage') / name
        dest = root / 'bailian' / name
        if dest.exists():
            raise SystemExit('Memory source already exists; inspect before replacing.')
        shutil.copy2(source, dest)
    main_file.write_text(changed)
    pathlib.Path('/tmp/oneapi-memory-backup-path').write_text(str(backup))
    print('backup=' + str(backup))
    print('new gateway route staged; runtime, database and nginx unchanged')


if __name__ == '__main__':
    main()
