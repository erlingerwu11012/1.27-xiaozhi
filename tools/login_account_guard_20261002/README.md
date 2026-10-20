# Login account guard — 2026-10-02

Published at 19:43:38 China time to https://realecho.cn and https://www.realecho.cn.

## Findings

Production login code contained no email constant or server-driven username replacement. Login/password fields stayed mounted while the modal was hidden and explicitly allowed browser credential autofill. This supports autofill as the likely cause; the user's own saved-password browser profile was not observed directly. A delayed public-configuration response also changed login type without checking whether the form was in use.

## Change

Only `main/manager-web/src/views/login.vue` changed on the SSH server. Fields mount only while the modal is open. Username/password are readonly until focused; delayed inactive input/change events and silent DOM replacements restore the selected values. Normal focused editing and Chinese input composition remain available. Login/register forms use separate component keys. Delayed configuration cannot switch an open form's login type. Passwords are not stored by this change.

The guard is a mitigation for browser credential filling, not a guarantee against every password-manager extension. An external fill firing a normal input event while the same field is focused can resemble intentional editing. Refresh and check the original browser profile after deployment; manually enter the password if autofill is blocked.

## Checks

Production build succeeded. Thirteen browser checks passed on each domain before and after publication, covering hidden inputs, focus editing, delayed configuration, inactive fill rejection, focused silent fill restoration, intentional account edits, IME, captcha refresh, registration switching, submitted account, credential storage, page errors, and modal close. Login POSTs were intercepted with synthetic passwords: no genuine login, registration or database change occurred. HTTP 200 and the deployed index hash were independently checked on both public domains.

These simulations validate the implementation paths; they do not establish reproduction in the user's saved-password profile. The close check validates removed inputs; timer cleanup is additionally present in source.

## Deployment and rollback

Server: `root@121.40.239.140`.

Frontend source: `/root/prjs/xiaozhi-esp32-server/main/manager-web/src/views/login.vue`.

Static root: `/var/www/realecho-www`.

Backup: `/root/prjs/tmp/login-account-guard-20261002/backup-20261002T114338Z`.

Atomic index publication followed asset installation; old chunks remain for already open clients. No backend restart or Nginx configuration change was made.

To roll back this release after confirming no intervening release:

```sh
python3 /root/prjs/tmp/login-account-guard-20261002/deploy.py --rollback /root/prjs/tmp/login-account-guard-20261002/backup-20261002T114338Z
```

Evidence is in `evidence/`; the source diff is `login.vue.patch`. Local working build files are in `build/login_account_guard_20261002/`. Nothing was pushed to a Git remote.
