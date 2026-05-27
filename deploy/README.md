# Deployment

The CI pipeline (`push` to `main`) handles all subsequent deploys automatically.  
This guide covers the **one-time setup** required on a new server.

## Prerequisites

- Ubuntu/Debian server with nginx, Python 3.10+, and `rsync` installed
- A `deploy` user with SSH access and write permissions to the deployment directory
- An existing nginx vhost for the domain you are deploying to

---

## 1. Server setup (as root)

```bash
# Install the systemd service
cp <deployment-dir>/current/deploy/reed.service /etc/systemd/system/reed.service
systemctl daemon-reload
systemctl enable --now reed

# Allow the deploy user to restart only this service — nothing else
echo 'deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart reed' \
  > /etc/sudoers.d/deploy-reed
chmod 440 /etc/sudoers.d/deploy-reed
```

> **Note:** `/bin/systemctl` may be `/usr/bin/systemctl` on your system.  
> Check with `which systemctl` and update the sudoers line accordingly.

---

## 2. First deploy (as the `deploy` user)

SSH in as `deploy`, then run the steps below **once**.  
After this, the CI takes over on every push to `main`.

```bash
# Create the directory structure (adjust the base path to match your server)
mkdir -p <deployment-dir>/{releases,shared/{venv,data,storage}}

# Bootstrap the shared venv and install all dependencies
# (slow the first time due to git-based packages in pyproject.toml)
python3 -m venv <deployment-dir>/shared/venv
<deployment-dir>/shared/venv/bin/pip install --upgrade pip

# Trigger the first CI deploy via GitHub Actions (push to main),
# or manually rsync the repo and run:
#   <deployment-dir>/shared/venv/bin/pip install -e <deployment-dir>/releases/<first-release>
#   ln -sfn <deployment-dir>/releases/<first-release> <deployment-dir>/current
```

Make sure the `shared/storage` directory is writable by the user the service runs as
(see `User=` in `reed.service`) and readable/writable by the `deploy` user for rsync.
If they differ, add both to a shared group and set group-write permissions:

```bash
# Example: service runs as www-data, deploy user is deploy
usermod -aG www-data deploy
chown -R deploy:www-data <deployment-dir>/shared/storage
chmod -R g+rwX <deployment-dir>/shared/storage
```

---

## 3. Nginx

The service listens on `127.0.0.1` on the port defined in `reed.service` (default `8765`).  
Add the contents of `nginx-reed.conf` inside the `server { }` block of your vhost,
adjusting the `location` path and port if needed:

```bash
nginx -t && systemctl reload nginx
```

The service will then be reachable at `https://<your-domain>/<subpath>/`.  
OpenAPI docs: `https://<your-domain>/<subpath>/docs`

---

## 4. GitHub Actions secrets

In the repository → **Settings → Secrets and variables → Actions**, add:

| Secret | How to get it |
|---|---|
| `WEB_SERVER_PRIVATE_KEY_B64` | `base64 -w0 ~/.ssh/id_ed25519` (the deploy user's private key) |
| `KNOWN_HOSTS` | `ssh-keyscan <server-ip>` |

Also update the `env` block at the top of `.github/workflows/ci.yml` to match your server:

```yaml
env:
  SSH_HOST: "<server-ip>"
  SSH_USER: "deploy"
  REMOTE_BASE: "<deployment-dir>"
```

---

## 5. Persistent data

Files that must survive across releases live in the shared directory:

| Path | Contents |
|---|---|
| `<deployment-dir>/shared/data/` | Brightway databases, model files |
| `<deployment-dir>/shared/storage/` | Uploaded archives and job results |
| `<deployment-dir>/shared/venv/` | Python virtual environment |

Each release symlinks `data/` into itself; the venv is shared across all releases.

---

## Useful commands

```bash
# Service management (on the server)
systemctl status reed          # check status
sudo systemctl restart reed    # manual restart
journalctl -u reed -f          # follow logs
journalctl -u reed -n 100      # last 100 lines

# Release management (as deploy)
ls -lt <deployment-dir>/releases/   # list releases, newest first
readlink <deployment-dir>/current   # see active release
```
