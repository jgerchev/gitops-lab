# Guest-only bootstrap

**Latest live attempt:** release downloads/checksums succeeded, K3s binary/config
and enabled service were installed, but host swap monitoring triggered guest
shutdown during service startup. Kubernetes readiness is unverified; Argo CD was
not reached. VM is off; its next boot will attempt K3s automatically. See the
top-level README before retrying. This supersedes historical worker-only status.

Host prerequisites have now been approved and installed by the coordinator.
**This worker performs no host operations or live deployment.** Nothing here
installs host packages, runs Terraform, changes existing services, pushes Git,
or publishes images. Run only against the coordinator-created isolated VM.

## Ownership and pins

- Ubuntu 24.04 amd64 **VM** named `gitops-lab`; SSH account `lab`.
- K3s **v1.37.2+k3s1**, one server/agent, API on the private NAT guest,
  Pod CIDR `10.42.0.0/16`, Service CIDR `10.43.0.0/16`.
- Argo CD **v3.6.1**, official **non-HA** `manifests/install.yaml` (not HA/core).
  Kubernetes 1.37 is in this release's tested compatibility range.
- `versions.env` records exact URLs and SHA-256 values. K3s hash comes from
  `https://github.com/k3s-io/k3s/releases/download/v1.37.2%2Bk3s1/sha256sum-amd64.txt`;
  Argo manifest hash was computed from the version-tagged upstream bytes.
  Both public artifacts were fetched and checked locally on 2026-11-14.

K3s's Kubernetes API retains its guest-network listener so pods can reach the
`kubernetes` Service via the node-IP endpoint. Do not forward guest port 6443
from the router/host or expose this lab network publicly. This is distinct from
the Argo API, which stays ClusterIP-only. Administrative kubectl still uses
root's loopback kubeconfig inside the guest.

There is **no mutable installer script**: the checksummed K3s binary is installed
with the reviewed systemd unit/config in this directory. A changed release tag
fails checksum validation. SHA-256 pins provide repeatability, not independent
upstream signature/provenance verification. Container image references inside
the pinned Argo manifest remain upstream version tags, not image digest pins.

Argo, its CRDs/RBAC and the `argocd` namespace are **bootstrap-owned**, never part
of the application's GitOps tree. The AppProject permits only Deployment,
Service and Ingress in `gitops-lab` from the one contracted repository. The one
cluster-scoped exception is **core Namespace**, required by the merged
`gitops/namespace.yaml`; the app namespace is GitOps-owned, not precreated by
bootstrap. No other cluster resources, RBAC, Secrets or namespaced Argo access
are delegated.

**Namespace permission is a deliberate lab-only tradeoff:** AppProject kind
allowlists cannot restrict cluster-scoped resources by `metadata.name`. Review
Git changes so the only Namespace resource remains `gitops-lab`; do not point
this project at untrusted source or use this as a production security boundary.
Namespace pruning can delete the app namespace and everything in it. Bootstrap
does not impose conflicting ownership/security labels on that Namespace.

`gitops/` must not contain Argo resources. The Application uses native Argo
auto-detection: either plain YAML at `gitops/` or `gitops/kustomization.yaml`;
no forced directory generator.
It tracks `https://github.com/jgerchev/gitops-lab`, `main`, with automatic prune
and self-heal. Empty source pruning is disabled. Never put credentials in Git.

## Prerequisites and run

Local: Bash, OpenSSH client, curl, GNU timeout, tar, sha256sum and standard core
utilities. Guest: systemd, Python 3, curl-independent base utilities, flock,
cloud-init (if present it must finish successfully), and **noninteractive guest
sudo**. Ubuntu cloud images normally supply these; missing tools cause a clear
failure, not implicit apt changes. The guest needs outbound HTTPS and access to
container registries and the Git repository. Recheck the contract's network
overlap and host resource budget before any provisioning.

Verify SSH host keys out of band for **both** jump host and guest and populate
known_hosts before running; key checking is strict and passwords are disabled.
Keep the private SSH key outside the checkout. Use the Terraform `vm_ip` output;
the contract's expected value below is an example, not discovery of a live VM.

```bash
bash bootstrap/bootstrap.sh --help
bash bootstrap/bootstrap.sh --render  # offline, no network or writes

# Direct access from virtualization host/workstation with a route to guest:
bash bootstrap/bootstrap.sh --target lab@192.168.250.10 --identity ~/.ssh/id_ed25519_homeserver

# Workstation through virtualization host:
bash bootstrap/bootstrap.sh --target lab@192.168.250.10 \
  --jump homeserver --identity ~/.ssh/id_ed25519_homeserver \
  --known-hosts ~/.ssh/known_hosts
```

`--port` sets the guest SSH port. Repeat `--ssh-option Name=value` for extra
OpenSSH options (for example ProxyJump configuration in `~/.ssh/config`). Do not
override strict host-key checking or enable forwarding to non-loopback addresses.
**ProxyJump does not inherit the guest's `-i` option.** Configure the jump host
identity/port under its own entry in the workstation's `~/.ssh/config`:

```sshconfig
Host homeserver
    HostName HOME_SERVER_ADDRESS
    User HOME_SERVER_USER
    IdentityFile ~/.ssh/id_ed25519_homeserver
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

The guest cloud-init must contain the **public** half of that same workstation
key. The private key stays on the workstation: **no scp to the host and no SSH
agent forwarding** are needed. Use `--jump homeserver` (or `-J homeserver` in
the tunnel examples below) and `--identity ~/.ssh/id_ed25519_homeserver` for
bootstrap; `-i ~/.ssh/id_ed25519_homeserver` supplies the guest identity for
manual SSH/tunnel commands. An SSH config `Host` entry for the guest may also
set this IdentityFile. `--known-hosts` applies to the guest connection; configure
any custom jump-host known_hosts file under the `homeserver` entry too.

The script accepts only a `lab@...` target and the remote script additionally
requires a VM, Ubuntu 24.04 amd64, and the exact guest hostname. These safeguards
are not a replacement for selecting the correct target.

Downloads use HTTPS-only redirects, 10-second connection and 300-second transfer
timeouts with two bounded retries. SSH uses a 10-second connection timeout,
keepalives and a 35-minute transport deadline. Root guest work has a **30-minute
overall deadline**, a 10-second exclusive lock wait, bounded cloud-init/startup,
API/Traefik waits, 30-second API requests and bounded rollout waits. A slow guest
can hit the total deadline before the sum of individual waits: inspect, then
repeat. No loop retries indefinitely. No private keys/kubeconfigs/passwords are
copied back, and neither shell uses tracing. Do not run with `bash -x` or record
credential-retrieval terminals.

## Repeats, failure, explicit mismatch handling

Running the same command again rechecks both artifacts, ensures systemd is
enabled/running without restarting a healthy server, and server-side-applies
declarative resources. Root-only ownership/version records live at
`/var/lib/gitops-lab-bootstrap/`. A partial owned run can resume. Configuration,
binary hash/version, ownership or Argo image version mismatches **stop** before
an upgrade/reinstall; no uninstall/reset command is invoked. Existing foreign
K3s/Argo installations are not adopted. Unexpected config/systemd drop-ins also
stop the run. An interrupted/corrupted file may require manual investigation.

For a mismatch, inspect the recorded versions and diagnostics below. Do not
delete the ownership record to force adoption. There is deliberately no
`--upgrade`/`--force` escape hatch: use a separately reviewed migration or have
the coordinator recreate **only this disposable lab VM** and bootstrap afresh.
Keep Terraform state outside the guest/checkout. Do not destroy anything from
this script.

Kubeconfig and its directory remain root-owned (`0600` file, `0700` directory).
Run `sudo -n k3s kubectl` **inside the guest**; never chmod kubeconfig readable by
`lab` or copy it to Git. Full Argo install uses **server-side apply**, avoiding
oversized last-applied annotations on CRDs, then waits for CRD `Established`
before applying AppProject/Application. Field conflicts are **not forced**;
inspect competing managers rather than transferring ownership silently.
Readiness checks explicitly cover the sole node, Traefik, all six Argo
Deployments and its single controller StatefulSet.

Success means bootstrap infrastructure is ready and the Application exists,
**not** that application sync or HTTP acceptance has passed. The Git tree,
published images/digests and any private-repository credentials must exist first.

## Loopback-only Argo access

Argo's Service stays **ClusterIP**; no Argo Ingress, NodePort, LoadBalancer,
router forwarding, LAN listener or public URL is created. Do not add any.

Terminal A, workstation (leave running):

```bash
ssh -J homeserver -i ~/.ssh/id_ed25519_homeserver -t lab@192.168.250.10 \
  'sudo -n k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml -n argocd port-forward --address 127.0.0.1 service/argocd-server 8443:443'
```

Terminal B, workstation (leave running):

```bash
ssh -J homeserver -i ~/.ssh/id_ed25519_homeserver -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8443:127.0.0.1:8443 lab@192.168.250.10
```

Open `https://127.0.0.1:8443`. Argo initially uses a self-signed certificate;
check it through the verified SSH connection. Keep TLS enabled on Argo. Both
forwards terminate on loopback; stop them with Ctrl-C. If using different SSH
identities, add the same identity/config options used for bootstrap.

Initial login is `admin`. Retrieve its generated password only into a trusted,
unrecorded local clipboard/password manager, never a log or shell argument. For
example, on a Wayland workstation with `wl-copy` installed:

```bash
ssh -J homeserver -i ~/.ssh/id_ed25519_homeserver lab@192.168.250.10 \
  'sudo -n k3s kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"' \
  | base64 --decode | wl-copy
# Paste into UI, change password there, then clear clipboard:
wl-copy --clear
```

After changing it, delete `argocd-initial-admin-secret` with guest root kubectl.
Repeats do not reset the admin password. Configure any private repository's
read-only access in the UI through this tunnel, not in committed manifests or
command-line token arguments. Treat a clipboard as sensitive and clear history.

## Application traffic and acceptance

Traefik is deliberately enabled. The app path is workstation loopback tunnel →
SSH host → guest Traefik port 80 → `gitops-lab` ClusterIP Service → Pod port 8080.
This is separate from the Argo tunnel; no DNS/Caddy/Pi-hole changes are needed.

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8081:192.168.250.10:80 homeserver
# Another local terminal:
curl --fail --max-time 10 -H 'Host: gitops-lab.test' http://127.0.0.1:8081/
```

Inside guest, after the public source/images or private access are available:

```bash
sudo -n k3s kubectl -n argocd wait --for=jsonpath='{.status.sync.status}'=Synced application/gitops-lab --timeout=300s
sudo -n k3s kubectl -n argocd wait --for=jsonpath='{.status.health.status}'=Healthy application/gitops-lab --timeout=300s
sudo -n k3s kubectl -n gitops-lab rollout status deployment/gitops-lab --timeout=300s
```

Then perform and record the assignment's v1→v2, self-heal, broken rollout/revert,
restart and destroy/recreate exercises. Host memory/swap/disk measurements and
Terraform lifecycle remain coordinator-owned; stop the lab if existing services
are affected. None of these acceptance exercises has been performed here.

## Diagnostics (inside the guest unless noted)

```bash
sudo -n systemctl status k3s --no-pager
sudo -n journalctl -u k3s --since '-15 min' --no-pager
sudo -n k3s --version
sudo -n stat -c '%a %U:%G %n' /etc/rancher/k3s/k3s.yaml
sudo -n k3s kubectl get nodes -o wide
sudo -n k3s kubectl -n kube-system get pods,deployments,services
sudo -n k3s kubectl -n argocd get pods,deployments,statefulsets,services
sudo -n k3s kubectl -n argocd get application gitops-lab
sudo -n k3s kubectl -n argocd describe application gitops-lab
sudo -n k3s kubectl -n argocd logs deployment/argocd-repo-server --tail=100
sudo -n k3s kubectl -n gitops-lab get deployments,pods,services,ingresses
sudo -n k3s kubectl -n gitops-lab describe deployment gitops-lab
sudo -n k3s kubectl -n gitops-lab get events --sort-by=.lastTimestamp
```

Use `describe pod NAME` for ImagePullBackOff/probe/scheduling failures. Missing
source/digests: finish publication through the coordinator, not by changing pins
to `latest`. Permission denial: compare rendered resources with AppProject's
allowlist and any Git-managed namespace PSS; do not grant wildcard cluster
rights. SSA conflict: inspect resource managedFields and resolve explicitly.
Missing Traefik: inspect
`kube-system` HelmChart/HelmChartConfig and startup logs, not `--disable traefik`.
SSH/sudo failure: fix only guest access under the approved provisioning process;
this is not permission to change the host. Redact logs before sharing; never
dump Secrets, kubeconfig, K3s tokens or private repository credentials.

## Local validation only

```bash
bash -n bootstrap/bootstrap.sh bootstrap/guest.sh bootstrap/versions.env
shellcheck -x bootstrap/bootstrap.sh bootstrap/guest.sh bootstrap/versions.env
# Python 3 + PyYAML in an existing environment or venv outside the checkout:
python3 bootstrap/test_static.py
# Optional: use independently downloaded public artifacts to check checksums,
# upstream YAML/non-HA properties, and mocked transport (NO remote execution):
python3 bootstrap/test_static.py \
  --argocd-manifest /PATH/OUTSIDE/CHECKOUT/argocd-install.yaml \
  --k3s-binary /PATH/OUTSIDE/CHECKOUT/k3s
```

The renderer, syntax/static tests and mocked transport do **not** prove guest
boot, runtime compatibility, readiness, repeat execution on a real cluster,
Application health or acceptance. These remain **unverified by this worker: no
cluster was contacted**. Host prerequisites were reported installed, but that
does not turn local checks into a successful live deployment.
