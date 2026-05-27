# Deployment

The CI pipeline (`push` to `main`) handles all subsequent deploys automatically.  
This guide covers the **one-time setup** required on a new server.

## Prerequisites

- Ubuntu/Debian server with nginx, Python 3.10+, and `rsync` installed
- A `deploy` user with SSH access and write permissions to `/home/bonsai/reed/`
- A `bonsai.uno` nginx vhost already in place

---

## 1. Server setup (as root)

```bash
# Install the systemd service
cp /home/bonsai/reed/current/deploy/reed.service /etc/systemd/system/reed.service
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
# Create the directory structure
mkdir -p /home/bonsai/reed/{releases,shared/{venv,data,storage}}

# Bootstrap the shared venv and install all dependencies
# (slow the first time due to git-based packages in pyproject.toml)
python3 -m venv /home/bonsai/reed/shared/venv
/home/bonsai/reed/shared/venv/bin/pip install --upgrade pip

# Trigger the first CI deploy via GitHub Actions (push to main),
# or manually rsync the repo and run:
#   /home/bonsai/reed/shared/venv/bin/pip install -e /home/bonsai/reed/releases/<first-release>
#   ln -sfn /home/bonsai/reed/releases/<first-release> /home/bonsai/reed/current
```

You also need to make sure that the folder that is used for storing the files is already available and
that both the deploy user can write and also the www-data user can read and write to theh folder.


---

## 3. Nginx

Add the contents of `nginx-reed.conf` inside the `server { }` block of your bonsai.uno vhost:

```bash
nginx -t && systemctl reload nginx
```

The service will be reachable at `https://bonsai.uno/reed/`.  
OpenAPI docs: `https://bonsai.uno/reed/docs`

---

## 4. GitHub Actions secrets

In the repository → **Settings → Secrets and variables → Actions**, add:

| Secret | How to get it |
|---|---|
| `WEB_SERVER_PRIVATE_KEY_B64` | `base64 -w0 ~/.ssh/id_ed25519` (the deploy user's private key) |
| `KNOWN_HOSTS` | `ssh-keyscan 162.55.167.96` |

---

## 5. Persistent data

Files that must survive across releases live in the shared directory:

| Path | Contents |
|---|---|
| `/home/bonsai/reed/shared/data/` | Brightway databases, model files |
| `/home/bonsai/reed/shared/storage/` | Uploaded archives and job results |
| `/home/bonsai/reed/shared/venv/` | Python virtual environment |

Each release symlinks `data/` into itself; the venv is shared across all releases.

---

## Useful commands

```bash
# Service management (on the server)
systemctl status reed          # check status
sudo systemctl restart reed    # manual restart
journalctl -u reed -f          # follow logs

# Release management (as deploy)
ls -lt /home/bonsai/reed/releases/   # list releases, newest first
readlink /home/bonsai/reed/current   # see active release
```
