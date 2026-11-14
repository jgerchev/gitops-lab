# Isolated libvirt infrastructure

This directory manages **only** `gitops-lab`: one dedicated directory pool,
one NAT network, an immutable base image, a **25 GiB qcow2 overlay**, cloud-init
ISO/upload volume, and one KVM domain (**2 vCPU / 3072 MiB**). No Docker paths,
production networks, DNS services, firewall rules, or existing pools are managed.
The root overlay depends on the base: keep both until Terraform destroys them.

## Current status and prerequisites

The coordinator installed the explicitly approved QEMU/libvirt prerequisites,
verified system-libvirt access and generated/reviewed a seven-create lab-only
plan. Apply created all resources after correcting the cloud-init volume format
to `iso` (libvirt readback detects ISO despite QEMU's CD-ROM raw driver). The
guest became SSH-accessible, but the host swap-safety monitor triggered and the
VM was shut off. After read-only inspection and explicit user authorization,
a boot-only retry left the VM running with cloud-init done, an expanded disk,
stable measured memory and healthy production endpoints. Kubernetes has not
been installed. See the
top-level README for current live results; worker validation alone
does not establish lifecycle acceptance. Prerequisite approval
does not imply permission to alter Pi-hole or other services.

On Ubuntu 24.04 the scoped prerequisite package set is `qemu-kvm`, `qemu-utils`,
`libvirt-daemon-system`, and `libvirt-clients`. An authorized operator must review
package/service/firewall effects before installation, arrange access to
`qemu:///system` (libvirt membership is privileged), and verify KVM. Do not run
Terraform as root or disable AppArmor/SELinux to work around access problems.
The provider builds the cloud-init ISO itself; no external ISO utility required.
Scripts require Python >=3.11 (Ubuntu 24.04 supplies 3.12). Terraform must be
**1.17.2**, provider **dmacvicar/libvirt 0.9.9**, pinned in the committed lock file.

Read-only checks on the approved virtualization host, **before any plan/apply**:

```sh
free -h
vmstat 1 10
docker stats --no-stream
df -h /var/lib/libvirt
test -c /dev/kvm
virsh -c qemu:///system list --all
virsh -c qemu:///system net-list --all
virsh -c qemu:///system pool-list --all
ip -4 address
ip -4 route show table all
ss -lntup
```

Inspect existing libvirt network XML, Docker network CIDRs, VPN routes and LAN
CIDRs, including currently disconnected VPNs. Stop if `192.168.250.0/24`,
`10.42.0.0/16`, or `10.43.0.0/16` overlaps. Stop if resource names, bridge
`virbr-gitops`, MAC `52:54:00:47:4f:50`, or pool directory already belong to
anything else; never import/delete an unrelated resource. Verify that
`/var/lib/libvirt/gitops-lab` is on SSD with room for the base, a fully grown
25 GiB root disk, and safe headroom. Monitor memory under typical/peak Immich
load; sustained swap I/O or impact on existing services blocks deployment.
Do not create the pool inside production Docker directories.

### Pi-hole / DNS coexistence

Pi-hole owns wildcard TCP/UDP port 53. The **lab network only** has
`dns = { enable = "no" }`, the actual 0.9.9 schema (not `dns.enabled`). Libvirt's
dnsmasq retains DHCP with a MAC reservation but disables its DNS listener.
The guest ignores DHCP-provided DNS and uses **1.1.1.1 and 9.9.9.9 through NAT**.
It never uses `192.168.250.1` for DNS. Check external DNS reachability under the
existing policy; if unavailable, stop and obtain an approved alternative. Do
not change Pi-hole, router, VPN, Caddy, or host security controls. NAT is not a
security boundary against outbound access to the LAN.

## Immutable image and upstream schema

Official archive build: **Ubuntu Server 24.04 amd64, release-20261017**, QCOW2:

```text
https://cloud-images.ubuntu.com/releases/noble/release-20261017/ubuntu-24.04-server-cloudimg-amd64.img
SHA256: 04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94
```

Hash selected directly from the official dated
[SHA256SUMS](https://cloud-images.ubuntu.com/releases/noble/release-20261017/SHA256SUMS),
not a moving `current`/`release` URL. `fetch-image.py` streams to a mode-0600
temporary file outside Git, verifies the pinned hash, then atomically publishes
without overwriting. Cached files are reverified. Terraform rechecks SHA256
before the base upload. Never resize/modify the cached source. Cloud-init grows
the guest partition/filesystem on the fresh 25 GiB overlay. Availability of the
archive can change; failure is intentional, never silently choose a newer image.
The full image was not downloaded during offline implementation validation.

Researched **tagged v0.9.9** documentation:
[domain](https://github.com/dmacvicar/terraform-provider-libvirt/blob/v0.9.9/docs/resources/domain.md),
[network](https://github.com/dmacvicar/terraform-provider-libvirt/blob/v0.9.9/docs/resources/network.md),
[pool](https://github.com/dmacvicar/terraform-provider-libvirt/blob/v0.9.9/docs/resources/pool.md),
[volume](https://github.com/dmacvicar/terraform-provider-libvirt/blob/v0.9.9/docs/resources/volume.md),
[cloud-init](https://github.com/dmacvicar/terraform-provider-libvirt/blob/v0.9.9/docs/resources/cloudinit_disk.md).
Also inspected tagged cloud-init/volume resource source and the **installed
provider's JSON schema**. Some tagged examples themselves are stale: actual
`os.boot_devices` is `[{ dev = "hd" }]`, volume format is
`target = { format = { type = "qcow2" } }`, and cloud-init generates a local ISO
which a separate `libvirt_volume` uploads. Do not substitute 0.8.x examples.

## External runtime and safe commands

Only the coordinator operates Terraform, on the virtualization host. Never use
plain `terraform plan/apply/destroy` in this checkout. `scripts/tf.py` requires an
absolute external runtime and `TF_DATA_DIR`, forces the local backend outside Git,
serializes invocations with `flock`, preserves backend locking, restricts CLI
commands/flags, checks initialized backend paths before state operations, and
requires a separate apply gate. No alternate workspaces, hidden `TF_CLI_ARGS*`,
`-lock=false`, arbitrary plan paths, or private-key variables are supported.
All generated state, backups, plans, ISO files, logs, and provider data stay
outside the checkout. Runtime directories are 0700; state/plans/ISO files 0600.
Provider binaries retain executable permissions. Keep runtime on persistent
host storage, **not in the guest or /tmp** for actual deployment.

From the repository root, on the approved host:

```sh
umask 077
export LAB_RUNTIME_DIR="$HOME/.local/state/gitops-lab"
export TF_DATA_DIR="$LAB_RUNTIME_DIR/terraform-data"
# Optional if terraform is not on PATH:
# export TERRAFORM=/absolute/path/to/checksum-verified/terraform
export TF_VAR_ssh_public_key="$(cat "$HOME/.ssh/id_ed25519.pub")"
python3 -B infra/scripts/fetch-image.py
python3 -B infra/scripts/tf.py fmt
python3 -B infra/scripts/tf.py init
python3 -B infra/scripts/tf.py validate
python3 -B infra/scripts/tf.py plan
python3 -B infra/scripts/tf.py show
```

Review **only lab resources**, quantities, memory/disk, network/DNS and disk
backing references. Plans embed public cloud-init data and should still be
treated as sensitive. After explicit approval for this reviewed plan:

```sh
LAB_APPROVE=apply python3 -B infra/scripts/tf.py apply
python3 -B infra/scripts/tf.py output
virsh -c qemu:///system net-dhcp-leases gitops-lab
virsh -c qemu:///system domblklist gitops-lab
ssh lab@192.168.250.10 'cloud-init status --wait; hostname; free -m; df -h /; resolvectl status'
python3 -B infra/scripts/tf.py plan
python3 -B infra/scripts/tf.py show
```

Expected second plan: `No changes`. `vm_name=gitops-lab` and
`vm_ip=192.168.250.10`; output IP is the reservation, **not readiness evidence**.
SSH uses the operator's SSH agent/config; no private key ever enters Terraform.
Use host-key checking. After deliberate recreation, verify the new guest's
fingerprint through a trusted path before replacing the old known-host entry.
Check `getent hosts cloud-images.ubuntu.com` in the guest and inspect guest
`resolvectl status`; recheck host Pi-hole health and existing home services.

Back up state outside the VM and checkout under restricted permissions (encrypt
off-host copies). With no Terraform writer running:

```sh
mkdir -p -m 700 "$LAB_RUNTIME_DIR/backups"
cp --no-clobber "$LAB_RUNTIME_DIR/state/terraform.tfstate" "$LAB_RUNTIME_DIR/backups/terraform-$(date -u +%Y%m%dT%H%M%SZ).tfstate"
```

Never delete/lose state before destroy. State is authoritative for cleanup;
provider metadata and saved plans are not a replacement for state backups.

## Stop, clean recreation, cleanup

Guest autostart is disabled to protect host memory after reboot. For an approved
graceful stop: `virsh -c qemu:///system shutdown gitops-lab`, then verify it is
off with `virsh -c qemu:///system domstate gitops-lab`. After a host reboot, first
inspect `virsh -c qemu:///system net-list --all` and start the inactive lab network
with `virsh -c qemu:///system net-start gitops-lab`. The lab network deliberately
does not autostart. Then restart with `virsh -c qemu:///system start gitops-lab`
and verify SSH/services. Configuration
has `running=true`, so a later apply may start a stopped guest again.

For full cleanup or the clean-disk recreation exercise, back up state and
check home-service health first. This destroys the entire disposable guest,
including its Kubernetes data; no production data may be stored there.

```sh
python3 -B infra/scripts/tf.py destroy-plan
python3 -B infra/scripts/tf.py show-destroy
# STOP and review: exactly the gitops-lab domain, volumes, seed, network, pool.
# Only after explicit cleanup approval:
LAB_APPROVE=apply-destroy python3 -B infra/scripts/tf.py apply-destroy
virsh -c qemu:///system list --all
virsh -c qemu:///system net-list --all
virsh -c qemu:///system pool-list --all
```

Verify lab volumes are removed and home services/Pi-hole remain healthy. A
directory pool can leave an empty directory; do not recursively remove paths.
For recreation run plan/show, obtain approval, apply, repeat guest checks and
bootstrap from `bootstrap/`; validate healthy v2 GitOps again. This explicit
destroy/recreate avoids mutating an in-use backing image. Do not declare the
lifecycle complete unless its live acceptance checks actually pass.

## Local implementation tests

The implementation worker checksum-verified the official Linux amd64 Terraform
1.17.2 ZIP (`e6f16b2f0b137ee5729caa8c4e79a3bae4ee261acd198a1fcfa8584a6296605b`)
against HashiCorp's official versioned SHA256SUMS and extracted only under
`/tmp/opencode`. Provider installation verified its signed release checksums;
the resulting `.terraform.lock.hcl` is committed. Local init uses an external
backend/data directory and does **not** connect to a virtualization host.

```sh
python3 -B -m unittest discover -s infra/tests -v
python3 -B infra/scripts/tf.py fmt
python3 -B infra/scripts/tf.py validate
# Optional schema inspection (redirect only outside Git):
python3 -B infra/scripts/tf.py schema > "$LAB_RUNTIME_DIR/provider-schema.json"
```

These check syntax/provider schema and guardrails, not runtime XML, DHCP, guest
boot, DNS reachability, SSH, host capacity, or idempotent/no-change live plans.
All live acceptance remains blocked until the coordinator's host readiness and
safety gates pass. No plan/apply is claimed as tested.

Recorded local results: **PASS** Terraform init (external backend + data),
`fmt -check -recursive`, `validate`, provider JSON-schema inspection, and **9/9
offline safety tests**. The tests cover outside-checkout paths/symlinks, hidden
flags/workspaces, corrupt downloads/cache, external backend flags, executable
permission preservation, explicit apply approval, and mismatched-backend refusal.
