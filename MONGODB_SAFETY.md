# MongoDB Safety Notes

Default paths:

- App directory: `/srv/taiko-web`
- Persistent data directory: `/srv/taiko-web-data`
- MongoDB data directory: `/srv/taiko-web-data/mongo`
- Redis data directory: `/srv/taiko-web-data/redis`
- Song file directory: `/srv/taiko-web-data/songs`
- MongoDB backup directory: `/srv/taiko-web/backups/mongodb/YYYYMMDD-HHMMSS/`

Safe commands:

```bash
sudo bash setup.sh install
sudo bash setup.sh update
sudo bash setup.sh backup-db
sudo bash setup.sh restore-db /srv/taiko-web/backups/mongodb/YYYYMMDD-HHMMSS/mongodump
sudo bash setup.sh repair
```

`setup.sh update` does not delete MongoDB data. When existing data is detected, it pauses application writers (`taiko-web-app` and/or the `taiko-web` systemd service), keeps MongoDB online, creates a `mongodump` backup, then updates and starts the new app service. If the backup or update fails before the app is replaced, the script attempts to restart the previously running app service.

`setup.sh backup-db` uses the same consistency-first behavior: pause app writes, run `mongodump`, then resume the app service that was running before the backup.

`setup.sh` keeps an existing `.env` file and only appends missing keys. It also excludes `.env` and `backups` from source sync deletion.

Dangerous database reset is explicit only:

```bash
sudo bash setup.sh reset-db
```

The reset command requires typing:

```text
I_UNDERSTAND_THIS_WILL_DELETE_MONGODB_DATA
```

Normal install and update flows must not run `docker compose down -v`, remove Docker volumes, or remove `/srv/taiko-web-data/mongo`.
