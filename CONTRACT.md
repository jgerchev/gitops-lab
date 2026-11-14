# Implementation contract

This repository is an isolated learning lab, not a production deployment.

- Git remote: https://github.com/jgerchev/gitops-lab; branch: main.
- Terraform: 1.17.2; dmacvicar/libvirt: 0.9.9. Use that provider's actual schema.
- Guest: fixed/checksummed Ubuntu Server 24.04 amd64 cloud image; the infra owner records the exact build and checksum in infra/.
- K3s: v1.37.2+k3s1; Argo CD: v3.6.1 (tested with Kubernetes 1.37).
- VM/domain/network/pool prefix: gitops-lab; 2 vCPU, 3072 MiB, 25 GiB root disk.
- Proposed NAT network: 192.168.250.0/24, gateway .1, VM .10; MAC 52:54:00:47:4f:50.
- Disable DNS on the lab network to coexist with an existing host wildcard DNS listener. Keep DHCP and explicitly configure guest resolvers; no host DNS changes.
- Guest SSH user/hostname: lab / gitops-lab. Public SSH key is an input; private keys never enter Terraform.
- Terraform outputs: vm_name, vm_ip. Run against qemu:///system on the virtualization host.
- Pool path: /var/lib/libvirt/gitops-lab. Never use production Docker directories.
- Local backend path and TF_DATA_DIR must be supplied outside the checkout. Plans and state backups stay outside the checkout and guest, mode 0600/0700.
- K3s Pod CIDR: 10.42.0.0/16; Service CIDR: 10.43.0.0/16. Recheck network conflicts before apply.
- App/namespace/Argo Application/AppProject: gitops-lab. Service: gitops-lab, port 80 -> container 8080.
- Ingress: gitops-lab.test, ingressClassName traefik; access via loopback SSH tunnel and Host header, no DNS changes.
- Image: ghcr.io/jgerchev/gitops-lab-app:v1 and :v2. Never overwrite existing tags. Record published digests and deploy tag@sha256 references once available.
- Single replica; non-root UID 10001; readiness probe; requests 25m/32Mi, memory limit 64Mi (adjust only on evidence).
- GitOps directory: gitops/, plain manifests or Kustomize; Argo automated prune/selfHeal. Argo CD is non-HA, bootstrap-owned, not self-managed.
- Owners: infrastructure infra/; bootstrap bootstrap/; application app/, gitops/, .github/workflows/image-build.yml. Coordinator owns everything else.
- Workers must not touch the live home server, push, publish, or edit outside owned paths. Each works in its assigned branch/worktree and commits only owned changes.
- No production repository, Caddy, Pi-hole, VPN, router, Docker stack, security-control, or existing backup-job changes.
- Host prerequisites require separate approval. Only coordinator operates Terraform; never concurrent state writers.
- Full lifecycle ends after cleanup demonstration with recreated healthy v2 lab, unless safety checks block operation.

## Observed prerequisites

Read-only discovery confirmed GitHub identity and SSH access. After explicit user approval, QEMU/libvirt prerequisites were installed, the SSH user joined libvirt/kvm, and Terraform 1.17.2 was installed with verified checksum in user-owned lab tooling. System-libvirt access now works. Local Docker daemon is unavailable; image builds use GitHub-hosted runners. Do not report unperformed acceptance tests as passed.

## Historical safety stop and current retry status

Initial Terraform apply ultimately created all seven lab resources (ISO seed format corrected after provider readback). A bounded monitor triggered on five consecutive current swap-I/O samples during guest first boot. ACPI shutdown was followed by authenticated guest poweroff; the domain is confirmed off. No Kubernetes bootstrap or live application/lifecycle tests ran. Do not restart or apply without reviewing the failed capacity gate. State is retained and backed up on host and workstation outside Git. The public GHCR demo image has anonymous manifest access verified for both immutable releases.

Subsequent inspection established the largest swap burst preceded VM startup.
The user then explicitly authorized a boot-only retry. The VM is now running:
cloud-init done, SSH working, guest disk expanded; a two-minute corrected
per-QEMU/cgroup/host observation passed the announced retry gates and production
HTTP checks. No K3s/Argo installation occurred. See README for chronology,
telemetry-path correction, exact measurements and outstanding full acceptance.

Later user-authorized bootstrap attempt was interrupted by the 10-consecutive-
swap-I/O-sample gate during K3s startup. VM is now OFF. K3s binary/config/unit
were installed and the unit enabled, but readiness was not reached; next VM boot
will attempt K3s automatically. Argo CD was not reached. No OOM or production
HTTP/DNS failure was observed; do not interpret conservative gate failure as
proof of total RAM exhaustion. No automatic restart/retry or host tuning.
