# Application and image releases

Dependency-free Python HTTP server: `/` returns `gitops-lab v1` or
`gitops-lab v2`; `/readyz` and `/healthz` return HTTP 200. It listens on 8080
as UID/GID 10001. The pod has a read-only root filesystem, no service-account
token, no capabilities, no privilege escalation, and RuntimeDefault seccomp.
Requests are 25m CPU / 32Mi memory; memory limit is 64Mi. Container memory
usage and probe behavior still require validation in the lab; no container or
cluster execution is claimed here.

## Local tests (no Docker required)

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s app -p 'test_*.py' -v
```

Tests exercise real loopback HTTP for both releases, probes, HEAD, and 404;
mocked registry responses test fail-closed publication; updater tests never
modify the deployment. There are no pip dependencies or network calls in tests.

## Reproducible inputs

`app/Dockerfile` pins `python:3.13.5-alpine3.22` to the registry **index** digest
`sha256:37b14db89f587f9eaa890e4a442a3fe55db452b69cca1403cc730bd0fbdc8aaf`.
Verification used Docker Hub's anonymous pull-token endpoint and a GET of
`https://registry-1.docker.io/v2/library/python/manifests/3.13.5-alpine3.22`
with OCI/Docker index Accept headers. The `Docker-Content-Digest` header and
SHA-256 of the response bytes both matched the pinned digest. This is a fixed
baseline, not a claim that the historical base is the latest security patch.
Review/security-scan base updates before publishing; never repair a published
release by overwriting its tag.

The workflow builds only `linux/amd64`, matching the lab VM. The two build
definitions are the same Dockerfile with `RELEASE=v1` or `RELEASE=v2`, selecting
the corresponding checked-in `app/releases/<release>/version.txt`. No package
installation, mutable dependency resolution, or latest tags are used. On an
approved build machine (not the production host), the equivalent build inputs
are `docker build --build-arg RELEASE=v1 -t ghcr.io/jgerchev/gitops-lab-app:v1 app`
and the same command with both `v1` occurrences replaced by `v2`. These are
build-only examples, not an alternative publication path. BuildKit/provenance
metadata may differ between runs; registry digests are recorded, not predicted.

Action pins were verified via official GitHub repository tag-reference API:

- actions/checkout v4.2.2: `11bd71901bbe5b1630ceea73d27597364c9af683`
- docker/setup-buildx-action v3.11.1: `e468171a9de216ec08956ac3ada2f0791b6bd435`
- docker/login-action v3.5.0: `184bdaa0721073962dff0199f1fb9940f07167d1`
- docker/build-push-action v6.18.0: `263435318d21b8e681c14492fe198d362a7d2c83`

Each official `/repos/<owner>/<repo>/git/ref/tags/<version>` response identified
the listed SHA as a commit (not an unpeeled annotated tag).

## Publish once, after explicit approval

Both releases were published by the coordinator using the workflow. See
`published-images.json` for build digests/run links and anonymous-access status.
Do not expect a healthy rollout until pull access and verified digest pinning
are complete. The following describes how the one-time publication was done;
do not rerun it to replace these releases.

1. Merge reviewed application/workflow files onto the repository's `main`.
2. A repository/package administrator must allow this repository's Actions
   token to write the package (and organization policy must permit GHCR).
3. Manually dispatch **Publish one immutable lab release** on `main`, selecting
   **only v1** initially. Later dispatch v2 separately. There are no push, PR,
   schedule, or self-hosted-runner triggers. Runs on other branches/repos skip
   publication. Only this job has `packages: write`; `contents` remains read-only.
4. The authenticated GHCR gate refuses existing tags. Only a definite 404 with
   registry code `MANIFEST_UNKNOWN` or `NAME_UNKNOWN` allows publication; auth,
   network, and ambiguous failures stop it. If initial package/token setup
   prevents confirming absence, fix permissions separately and retry; do not
   bypass the check. One selected image is built and pushed once per successful
   release. If a run fails after pushing, do **not** retry to overwrite the tag:
   inspect the existing manifest and recover its digest instead.
5. Record the workflow summary's full `tag@sha256:...` reference. The workflow
   does not change manifests, commit, or deploy anything automatically.
6. **Separate administrator operation:** GHCR packages are initially private.
   In GitHub package settings, explicitly change `gitops-lab-app` visibility to
   **Public** if approved. A public source repository does not make its package
   public. Confirm anonymous pull access before deployment. Alternatively,
   bootstrap an imagePullSecret out-of-band; no credentials belong in Git.

Concurrency serializes publishers in this repository. GHCR does not provide
an atomic create-only tag PUT through this workflow: the absence check cannot
prevent a separate external publisher racing it. Treat this workflow as the
exclusive authorized publisher, restrict other package writers, and never
delete/reuse release tags. Existing v1/v2 are immutable by release policy, not
by an unsupported claim of GHCR server-side tag locking.

## Pin digests and change versions

After publication, independently inspect the selected tag's registry manifest
digest (for example with `docker buildx imagetools inspect` on an approved
build machine), compare with the workflow summary, then run from the checkout:

```sh
python3 app/set-image.py v1 'sha256:<actual 64 lowercase hex characters>'
git diff -- gitops/deployment.yaml
```

The placeholder above is deliberately rejected. Supply the actual published
digest. This helper validates syntax and exactly one known image line; it does
not verify registry existence. For the GitOps upgrade, publish v2 once, verify
its digest, then run the helper with `v2` and that digest. Review/commit/push the
manifest change through the coordinator's approved process; Argo CD follows Git.
Use a Git revert to restore a previous known-good digest, never retag the image.

## Bootstrap integration

`gitops/` contains plain manifests; the Argo Application should target this
directory with automated prune/selfHeal and namespace `gitops-lab`. The
bootstrap-owned AppProject must permit destination namespace `gitops-lab` on
the local cluster, the required namespaced Deployment/Service/Ingress kinds,
and cluster-scoped `group: ""`, `kind: Namespace` so `namespace.yaml` can sync.
Do not enable namespace auto-creation as a substitute for permitting this
tracked manifest. Argo orders Namespace before namespaced resources. This
namespace is lab-owned and may be pruned during approved cleanup.

Service `gitops-lab` maps port 80 to the named container port 8080; Traefik
Ingress matches `gitops-lab.test`. Single-replica desired state is one; default
RollingUpdate may temporarily run a second pod during upgrades. Traffic path:
loopback SSH tunnel through host → VM Traefik → ClusterIP Service → Pod.
After the coordinator creates the approved tunnel:

```sh
curl --fail -H 'Host: gitops-lab.test' http://127.0.0.1:8081/
```

Expected response is `gitops-lab v1` initially and `gitops-lab v2` after the
reviewed version update. No DNS/router/production service changes are needed.

## Known limitation of these immutable demo releases

The server is single-threaded and has no accepted-socket timeout. A stalled or
incomplete HTTP request can block other requests/probes and cause a restart.
These releases are for the isolated, SSH-tunneled exercise, not an untrusted
public endpoint. Fix request handling in a new release if expanding exposure;
do not overwrite v1/v2. Keep real private/stateful data out of this disposable VM.
