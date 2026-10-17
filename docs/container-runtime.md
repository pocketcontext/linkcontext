# Container runtime

The released container requires private primary S3 storage and a separate
Litestream SQLite replica bucket with separate credentials. One Python entrypoint
(`docker/entrypoint.py`) handles preflight validation, staged restore, S3 object
verification, and Litestream supervision. Direct local server development on
`127.0.0.1:8095` remains supported without S3 or Litestream; the container does
not support `LITESTREAM_DISABLED` or local-file fallback.

Supply all five `LINKCONTEXT_S3_` settings: `BUCKET`, `ENDPOINT`, `REGION`,
`ACCESS_KEY_ID`, and `SECRET_ACCESS_KEY`. `FORCE_PATH_STYLE` defaults to `true`.
Supply `LITESTREAM_BUCKET`, `LITESTREAM_PATH`, `LITESTREAM_ACCESS_KEY_ID`, and
`LITESTREAM_SECRET_ACCESS_KEY`, plus the appropriate endpoint and region.
Keep all values in private deployment configuration.

## Explicit initialization

Normal container startup requires an existing database or a recoverable replica. A fresh
installation requires a deliberate one-shot `init` invocation of the image with
the intended `/storage` volume and complete storage configuration. It refuses a
nonempty database directory or an existing replica. Then start that same image
normally with the same volume and configuration.

## Validation

Run `python3 tests/entrypoint.py` for synthetic safety regressions, including
failed staged restore, missing objects, malformed maintenance state, interrupted
initialization, credential handling and termination during preparation. With Docker
available:

```sh
docker build -t linkcontext:ci .
python3 docker/smoke.py config --image linkcontext:ci
python3 docker/smoke.py smoke --image linkcontext:ci
python3 docker/smoke.py restore --image linkcontext:ci
python3 docker/object_storage_smoke.py --image linkcontext:ci --minio-image linkcontext-minio-fixture:9e49d5e-7394ce0
```
