# Deployment: Vercel, Azure, Supabase, and GitHub Actions

## Production layout

- **Vercel:** Next.js frontend, connected to this GitHub repository with the project root set to `frontend`.
- **Azure Linux VM:** backend only: the FastAPI API and the separately containerized Claude browser host. Docker Compose keeps the browser management API and Chrome DevTools ports on the private container network. Caddy provides HTTPS for the API and browser sign-in viewer.
- **Supabase:** PostgreSQL and S3-compatible Storage.
- **Redis:** external Upstash Redis REST service; no Redis container runs on the VM.
- **GitHub Actions:** tests pull requests; on pushes to `main`, builds and publishes backend images to GHCR, runs database migrations against external PostgreSQL, then updates the Azure VM.

The frontend is not deployed to Azure. Vercel deploys `frontend/` from `main`; GitHub Actions builds and deploys only the backend. Keep the API to one running instance: the scheduler currently starts inside the API process, so multiple replicas could duplicate scheduled work.

## 1. Create Supabase resources

1. Create a Supabase project and keep the database password. For deployment, use newly rotated production credentials; do not reuse the local development `.env`.
2. Copy the **session pooler** PostgreSQL connection string on port `5432`. URL-encode special characters in its password and add `?sslmode=require`. This project uses SQLAlchemy with `psycopg2`; do not use a `postgresql+psycopg://` URL.
3. In Storage, create a bucket named **`uniflow-files`** before deploying. The current application storage helper attempts bucket creation but suppresses errors, so pre-create it and verify uploads/downloads with a test file.
4. Enable S3 access for Storage and obtain its endpoint, access key, and secret key. Put those in `S3_BUCKET_URL`, `S3_ACCESS_KEY`, and `S3_SECRET_KEY`. Keep the bucket private unless the product explicitly requires public files; verify that generated signed links work with the S3 endpoint before relying on them.
5. Free Supabase projects have storage/database quotas and may pause after inactivity. Configure backups/export important data and expect to resume a paused project.

## 2. Deploy the frontend on Vercel

1. Import `iahmedd-k/UnivFlow` in Vercel, set **Root Directory** to `frontend`, and select `main` as the production branch.
2. Add the production environment variable:

   ```text
   NEXT_PUBLIC_API_URL=https://api.example.com/api/v1
   ```

   Set it for Production and Preview as appropriate. It is a public URL and is embedded during the Next.js build.
3. Set the project’s Node.js version to **24.x** to satisfy the Firebase package engine requirements in the current lockfile.
4. Add the Clerk publishable key and any other frontend-only public configuration required by your authentication setup. Set frontend secrets only in Vercel environment settings.
5. Deploy once and record the production hostname, for example `univflow.vercel.app`. Use that exact hostname as `APP_DOMAIN` on the VM and as the backend `FRONTEND_URL`.
6. Vercel’s GitHub integration deploys previews for pull requests and production on pushes to the configured production branch.

## 3. Create the Azure VM

1. In the Azure for Students subscription, create a Linux Ubuntu VM in a region with a suitable quota. The API and headed Chromium browser host both run on this VM, so choose enough memory for both and start with one browser session. The current VM has 8 GiB RAM. Check the actual VM and disk cost in Azure before confirming—the student credit is limited, not a free always-on VM guarantee.
2. Use the Azure DNS hostname `univlfow.koreacentral.cloudapp.azure.com` for the API and browser viewer. It currently resolves to the VM public IP `52.231.79.144`. The frontend hostname is `univ-flow-bt12.vercel.app`.

3. In the Azure network security group, allow inbound TCP 80 and 443. Restrict SSH (TCP 22) to your own IP. **Do not allow inbound ports 7900, 12000-12199, or 22000-22199**: the browser viewer is routed through Caddy, and the management/CDP ports must remain private.
4. Install only Docker Engine and the Docker Compose plugin on Ubuntu. Do not install a local database or Redis; PostgreSQL, Redis, and object storage are external. Make sure the deployment SSH user can run Docker and owns its deployment directory.
5. In the VM home directory, create `univflow-deploy/`, copy `backend/deploy/docker-compose.azure.yml` and `backend/deploy/Caddyfile` there, and create `univflow-deploy/.env.production` from [`backend/deploy/.env.production.example`](../backend/deploy/.env.production.example). Set restrictive permissions:

   ```bash
   chmod 600 ~/univflow-deploy/.env.production
   ```

   Fill in the domains, Supabase connection string and S3 credentials, and integration settings. Generate independent `SECRET_KEY`, `BROWSER_SERVICE_TOKEN`, and `BROWSER_VIEWER_SECRET` values (for example, with `openssl rand -hex 32`). Never put production secrets in GitHub source files or the image.
6. Set `APP_DOMAIN=univ-flow-bt12.vercel.app` and `API_DOMAIN=univlfow.koreacentral.cloudapp.azure.com`. Caddy serves the API and routes `/viewer/*` and `/novnc/*` to the browser host using this same Azure hostname. It automatically obtains a certificate when DNS is correct and ports 80/443 are reachable.

The Compose stack serves only the API and browser viewer. The browser host has a persistent Docker volume for per-user sign-in profiles; that volume is not replaced during image updates. Back it up if users rely on saved sessions. Restrict access to the VM and profile data because browser profiles contain authentication cookies.

## 4. Configure application integrations

Set only the integrations the deployment will use in `.env.production`:

- `DATABASE_URL`: Supabase session-pooler URL described above.
- `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`: external Upstash Redis REST credentials, if using the Redis-backed cache and portal lock.
- `S3_BUCKET_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`: Supabase Storage S3 credentials.
- `APP_DOMAIN`, `API_DOMAIN`: hostnames without `https://`.
- `SECRET_KEY`, `BROWSER_SERVICE_TOKEN`, `BROWSER_VIEWER_SECRET`: unique, strong secrets.
- Clerk backend secrets and frontend publishable settings, with the Vercel hostname registered in Clerk.
- Google OAuth client credentials. Register `https://univlfow.koreacentral.cloudapp.azure.com/api/v1/auth/google` as an allowed redirect URI and ensure the configured scopes and consent settings match the app.
- AI provider and notification credentials, as needed.

The Compose file sets the internal browser service URL and CDP host to the Compose service name. Do not change these to `localhost`: in the API container that would point back to the API container, not Chrome.

Set the backend CORS origin through `APP_DOMAIN`/`FRONTEND_URL`; if the frontend uses additional custom domains, update the backend CORS configuration before using them.

## 5. Enable GitHub Actions deployment

The workflow is [`.github/workflows/ci-deploy.yml`](../.github/workflows/ci-deploy.yml). It runs the selected backend health test and API/browser container builds for pull requests targeting `main`. The rest of the backend suite and the full Claude assignment workflow are deferred to a later staging test. On a push to `main`, or a manual run dispatched from `main`, the Azure deployment job waits for the backend test and backend image builds, then validates the required deployment secrets, publishes versioned backend images to GHCR, copies runtime files from `backend/deploy/` to the VM, applies Alembic migrations against external PostgreSQL, and updates the backend Compose stack. Deployment is serialized, and the workflow waits for the API and browser host health checks before succeeding. It does not build or deploy the frontend; Vercel handles frontend deployment through its GitHub integration.

In GitHub, open **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
| --- | --- |
| `AZURE_VM_HOST` | VM public IP or DNS name; use the same value when collecting the host key |
| `AZURE_VM_USER` | Non-root deployment SSH username |
| `AZURE_VM_SSH_PRIVATE_KEY` | Private SSH key for that user; public key must be installed on the VM |
| `AZURE_VM_KNOWN_HOSTS` | Verified SSH host-key line for the VM |
| `GHCR_PULL_USERNAME` | GitHub username that can read the private GHCR packages |
| `GHCR_PULL_TOKEN` | Classic GitHub personal access token with `read:packages` for pulling the private images |

Obtain the VM SSH host key with `ssh-keyscan -H "$AZURE_VM_HOST"` and verify its fingerprint against the VM before storing the complete output as `AZURE_VM_KNOWN_HOSTS`; do not blindly trust an unverified key. The workflow checks that this host-key entry matches `AZURE_VM_HOST` and uses strict, non-interactive SSH verification. Keep GHCR packages private and grant the pull token access only to these packages. GitHub Actions uses the repository `GITHUB_TOKEN` with `packages: write` to publish.

Optionally add the repository Actions variable `API_DOMAIN` with the hostname serving the API. If unset, the workflow uses `univlfow.koreacentral.cloudapp.azure.com`.

The workflow targets `main`; configure `main` as the production branch in Vercel as well.

Backend tests and backend image builds are the only CI prerequisites for Azure deployment. Frontend builds and deploys are handled by Vercel.

### What happens on a deploy

1. A pull request runs backend tests and both backend container builds; it does not deploy.
2. A push to `main` or a manual **Run workflow** from `main` runs the same backend checks.
3. After backend tests and backend image builds pass, GitHub builds and pushes immutable backend images tagged with the commit SHA.
4. GitHub validates the required Azure/GHCR secrets and checks that the SSH known-hosts secret contains the configured VM host. It SSHes to the VM, uploads Compose/Caddy configuration, authenticates to GHCR, and runs `alembic upgrade head` against the external database before bringing up the new backend image tag. The workflow waits until Compose reports the API and browser host healthy.
5. Compose waits for API and browser-host health checks as part of rollout. After deployment succeeds, perform the separate cloud smoke test: verify the API from a browser, start a Claude browser session in Settings, sign in, and run one test assignment. The workflow does not create a browser profile or access a Claude account.
6. Vercel independently builds and deploys `frontend/` from the configured production branch.

For the first release, perform the one-time Supabase, Vercel, VM, DNS, `.env.production`, and GitHub secret setup above. Then push to `main` and watch **GitHub → Actions** and the Vercel deployment page. Check `https://api.example.com/health`, sign in to the frontend, start the Claude browser in Settings, test its browser viewer over HTTPS, and run one test assignment through to **ready for review**. Confirm no assignment is submitted automatically.

## Operational limits and follow-up

- Keep a single API instance while its in-process scheduler is enabled. Do not scale this Compose service horizontally.
- Start with `MAX_BROWSER_SESSIONS=1`; increase only after checking available memory and session stability.
- The Azure VM was resized to 2 vCPUs and 8 GiB of RAM. Keep `MAX_BROWSER_SESSIONS=1` initially and check actual memory use before increasing browser concurrency.
- The API health route checks both the process and a database query; inspect API logs as well during the staging smoke test.
- Set Azure budget alerts, monitor credits and disk usage, and stop/deallocate the VM when it is not needed. A budget alert is not a hard spending cap.
- The browser service is stateful and in-memory for live sessions. A browser-host restart stops active sessions; users may need to reopen the viewer. Persistent profiles retain sign-in data, but live browser processes do not survive restarts.
- Back up Supabase data and browser-profile storage before production use. Test restoring both.
