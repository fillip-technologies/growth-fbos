# Deploying to the aaPanel server

Production runs on the aaPanel server (72.61.240.178) at https://fbos.fillipsoftware.com.

| Repo | Checkout on the server | Deployed by |
|---|---|---|
| growth-fbos (backend) | `/www/wwwroot/fbos/backend` | `scripts/deploy_aapanel.sh`: `docker compose -f docker-compose.yml -f docker-compose.aapanel.yml up -d --build`, then waits for every service to be healthy |
| fbos_frontend | `/www/wwwroot/fbos/frontend` | its `scripts/deploy_aapanel.sh`: builds `clientadmin` into `dist-build/` and syncs it into `dist/`, the aaPanel site root |

The databases are on Hostinger, set in each service's `.env` on the server (not in git).
`docker-compose.aapanel.yml` keeps the local MySQL container off and publishes only the gateway,
on `127.0.0.1:8100`; the aaPanel site `fbos.fillipsoftware.com` proxies `/api/` to it (its URL
rewrite rules) and serves the client-admin build for everything else.

## CI/CD

Both repos have `.github/workflows/ci-cd.yml`:

- **Every push to `main`/`gkr` and every pull request:** backend runs each service's tests;
  frontend builds `clientadmin` and `superadmin`.
- **A push to `main` that passes:** the deploy job connects to the server over SSH and runs
  `fbos-deploy backend` (or `frontend`), which fast-forwards that checkout to `origin/main` and
  runs its `scripts/deploy_aapanel.sh`. A deploy can also be started by hand from the Actions tab
  (*Run workflow* on `main`).

Changes are deployed only through `main`: merge `gkr` into `main` to ship backend changes.

## One-time setup

### 1. Server: the deploy command and key

The deploy key may only run `/usr/local/bin/fbos-deploy` (copied from `scripts/fbos-deploy`),
whatever the client asks for.

Once these files are on `main`:

```bash
# the checkout predates the tracked override; the copy on the server is the same file
cd /www/wwwroot/fbos/backend && rm docker-compose.aapanel.yml && git pull --ff-only origin main
install -m 755 /www/wwwroot/fbos/backend/scripts/fbos-deploy /usr/local/bin/fbos-deploy
ssh-keygen -t ed25519 -N "" -C "github-actions-fbos-deploy" -f /root/.ssh/fbos_deploy
echo "restrict,command=\"/usr/local/bin/fbos-deploy\" $(cat /root/.ssh/fbos_deploy.pub)" >> /root/.ssh/authorized_keys
cat /root/.ssh/fbos_deploy        # the private key, for DEPLOY_SSH_KEY below
rm /root/.ssh/fbos_deploy         # GitHub keeps the only copy; the server needs just the .pub line
```

### 2. GitHub: secrets in both repos

In **growth-fbos** and **fbos_frontend**: *Settings → Secrets and variables → Actions → New
repository secret*:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | `72.61.240.178` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_SSH_KEY` | the private key printed above, including the `BEGIN`/`END` lines |
| `DEPLOY_KNOWN_HOSTS` | the output of `ssh-keyscan -t ed25519 72.61.240.178` |

The deploy job runs in the `production` environment (created on first run); add required
reviewers there to approve each deploy by hand.

## Deploying by hand

On the server, as root:

```bash
SSH_ORIGINAL_COMMAND=backend  /usr/local/bin/fbos-deploy
SSH_ORIGINAL_COMMAND=frontend /usr/local/bin/fbos-deploy
```
