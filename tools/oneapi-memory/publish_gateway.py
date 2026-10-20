"""Publish only the Bailian memory gateway route, with automatic rollback."""
import os
import pathlib
import shutil
import subprocess
import time
import urllib.request


def run(*args):
    subprocess.run(args, check=True)


def main():
    backup = pathlib.Path('/tmp/oneapi-memory-backup-path').read_text().strip()
    backup = pathlib.Path(backup)
    if backup.parent != pathlib.Path('/root/backups') or not backup.name.startswith('oneapi-memory-'):
        raise SystemExit('Invalid backup location')
    env_file = pathlib.Path('/etc/one-api-bailian.env')
    nginx_file = pathlib.Path('/etc/nginx/sites-available/api.realecho.cn')
    binary = pathlib.Path('/opt/one-api-bailian/one-api-bailian')
    candidate = pathlib.Path('/tmp/oneapi-memory-stage/one-api-bailian-candidate')
    env_original = env_file.read_text()
    nginx_original = nginx_file.read_text()
    if any(line.startswith('BAILIAN_MEMORY_CHANNEL_ID=') for line in env_original.splitlines()):
        raise SystemExit('Memory already configured; inspect before publication')
    if 'location ^~ /bailian/api/v2/apps/memory/' in nginx_original:
        raise SystemExit('Memory already published; inspect before publication')
    anchor = '    location = /bailian/api-ws/v1/inference {'
    if nginx_original.count(anchor) != 1 or not candidate.is_file():
        raise SystemExit('Publication precondition failed')
    block = '''    # Native memory API for the trusted device backend, using One API tokens.
    location ^~ /bailian/api/v2/apps/memory/ {
        client_max_body_size 1m;
        proxy_pass http://127.0.0.1:3011;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Origin $http_origin;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 100s;
        proxy_send_timeout 30s;
    }

'''
    modified = False
    try:
        env_file.write_text(env_original.rstrip('\n') + '\nBAILIAN_MEMORY_CHANNEL_ID=2\n')
        modified = True
        nginx_file.write_text(nginx_original.replace(anchor, block + anchor, 1))
        run('nginx', '-t')
        temporary = binary.with_name('one-api-bailian.memory-new')
        shutil.copy2(candidate, temporary)
        temporary.chmod(0o755)
        os.replace(temporary, binary)
        run('systemctl', 'restart', 'one-api-bailian.service')
        ready = False
        for _ in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1:3011/healthz', timeout=2) as response:
                    ready = response.status == 200
            except Exception:
                ready = False
            if ready:
                break
            time.sleep(0.5)
        if not ready:
            raise RuntimeError('Bailian extension did not become healthy')
        run('systemctl', 'reload', 'nginx')
        print('memory gateway published; extension healthy; nginx configuration valid')
        print('rollback backup=' + str(backup))
    except Exception:
        if modified:
            shutil.copy2(backup / 'gateway.env', env_file)
            shutil.copy2(backup / 'nginx.conf', nginx_file)
            temporary = binary.with_name('one-api-bailian.rollback')
            shutil.copy2(backup / 'one-api-bailian', temporary)
            temporary.chmod(0o755)
            os.replace(temporary, binary)
            subprocess.run(['systemctl', 'restart', 'one-api-bailian.service'], check=False)
            subprocess.run(['nginx', '-t'], check=False)
            subprocess.run(['systemctl', 'reload', 'nginx'], check=False)
            print('publication failed; runtime, environment and nginx restored from backup')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
