> Cloud deployment is disabled by default while LinkContext operates in local-first mode on `127.0.0.1:8095`. Follow [container runtime](container-runtime.md) and [CI and deployment](ci-and-deployment.md) for the container architecture when preparing a remote deployment.

# Local and container deployment

LinkContext uses the PocketContext revision in `POCKETCONTEXT_VERSION`. In local mode, it runs directly on `127.0.0.1:8095` with local SQLite storage in `./pb_data`. In container mode, the image serves HTTP on port 80, offers database-backed `GET /up`, and stores state in `/storage/pb_data` under tini and Litestream.

## Configuration

| Variable | Purpose |
| --- | --- |
| `BASE_URL` | Public origin; future cloud production uses `https://link.pocketcontext.com` (local mode uses `http://127.0.0.1:8095`). |
| `LINKCONTEXT_LOCAL_USER_EMAIL`, `LINKCONTEXT_LOCAL_USER_PASSWORD` | Optional localhost-only ordinary `users` account bootstrap for zero-friction local agent and reader sign-in. |
| `LINKCONTEXT_SUPERUSER_EMAIL`, `LINKCONTEXT_SUPERUSER_PASSWORD` | Operator provisioning at container startup. |
| `LINKCONTEXT_GOOGLE_CLIENT_ID`, `LINKCONTEXT_GOOGLE_CLIENT_SECRET` | Google OAuth credentials on the `users` auth collection. Both are required together. |
| `LINKCONTEXT_GOOGLE_WORKSPACE_DOMAIN` | Enables Google just-in-time signup for verified accounts matching this domain. |
| `LINKCONTEXT_TRUSTED_PROXY_HEADER` | Set to `X-Forwarded-For` behind ONCE. |
| `LINKCONTEXT_RATE_LIMITS` | Image defaults to `true`. |
| `LINKCONTEXT_S3_BUCKET`, `LINKCONTEXT_S3_ENDPOINT`, `LINKCONTEXT_S3_REGION`, `LINKCONTEXT_S3_ACCESS_KEY_ID`, `LINKCONTEXT_S3_SECRET_ACCESS_KEY` | Primary file storage configuration for container deployments. |
| `LINKCONTEXT_S3_FORCE_PATH_STYLE` | Optional `true` (default) or `false`. |
| `LITESTREAM_BUCKET`, `LITESTREAM_PATH` | Private replica bucket and LinkContext-only prefix (`once-pocketcontext/linkcontext`). |
| `LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY` | Credentials for the replica. |
| `LITESTREAM_ENDPOINT`, `LITESTREAM_REGION` | S3-compatible endpoint and region. |
| `LITESTREAM_SYNC_INTERVAL` | Defaults to `10s`. |
| `SMTP_ADDRESS`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAILER_FROM_ADDRESS` | Optional mail configuration. |

## Build and verification

```sh
python3 tests/integration.py --binary /path/to/pocketcontext
python3 tests/auth.py --binary /path/to/pocketcontext
python3 tests/oauth_integration.py --binary /path/to/pocketcontext
python3 tests/deploy.py --binary /path/to/pocketcontext
python3 tests/deploy_workflow.py
```
