# Common validation and deployment contract

`image.yml` owns push, pull-request and manual validation. It calls `test.yml`
once per run; the test workflow has no independent push/PR trigger. Both
application tests and container configuration/smoke/populated recovery run on
native AMD64 and ARM64 Linux using isolated synthetic data only.

Publication on main requires all application and container checks to pass. Each
architecture is built on its native runner and published by digest; the manifest
uses exactly those two digests. All external actions are pinned to full commits.

Remote deployment is disabled by default (`if: false && ...`) while LinkContext runs
in localhost-first mode (`127.0.0.1:8095`). When remote deployment to
`https://link.pocketcontext.com` is authorized in the future, it will use the
shared `once-pocketcontext-v2` dispatcher and its app-specific restricted SSH key.

After source changes, run the repository's README validation and the isolated
workflow checks:

```sh
python3 tests/deploy_workflow.py
```
