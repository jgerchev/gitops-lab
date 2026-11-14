# Home GitOps lab

Isolated Terraform/libvirt VM with K3s, Argo CD and a small Git-managed HTTP application.

See [the assignment](Home_Server_Lab_Assignment.md) and [the implementation contract](CONTRACT.md).

**Bootstrap interrupted by the swap-safety gate; VM is now shut off.** K3s binary/configuration and an enabled systemd unit were installed, but startup was cancelled by the monitored shutdown. Kubernetes readiness is unverified and **Argo CD was not installed**. A future VM boot will attempt to start K3s automatically. Review the measured swap behavior and safety criterion before restarting. Full assignment acceptance is incomplete; chronology and results are below.

## Scope and safety

This is a separate public repository, not part of an existing home-service deployment repository. Only resources prefixed `gitops-lab` belong to this exercise. Do not repurpose existing domains, networks, pools, Docker directories or backup jobs. Host package prerequisites survive lab cleanup; they are not Terraform-managed lab resources.

Prerequisites: an amd64 Linux KVM host, accessible `/dev/kvm`, libvirt system connection, SSH with public-key authentication, Git, curl, Python 3, image/seed tooling, and sufficient RAM/SSD headroom. `libvirt` group membership grants powerful host access; use only a trusted operator account. Local Docker is optional: images build on GitHub-hosted runners, never the production runner.

Pinned versions:

| Component | Version |
|---|---|
| Terraform | 1.17.2 |
| dmacvicar/libvirt | 0.9.9; committed lock file |
| Guest OS | Ubuntu Server 24.04 amd64; exact dated image/hash in `infra/` |
| K3s | v1.37.2+k3s1 |
| Argo CD | v3.6.1 non-HA; Kubernetes 1.37 is in its tested matrix |
| Application | v1/v2; published/verified digests in `app/published-images.json` |

## Start sequence

1. Collect baseline measurements on the virtualization host using `python3 scripts/preflight.py --samples 60`, saving output **outside Git**. Inspect all LAN, Docker, VPN, libvirt, Pod and Service subnets. Observe representative workload peaks, particularly photo processing, where practical.
2. Verify existing services and DNS before any lab operation. Use `MemAvailable`, not `MemFree`; ignore the first vmstat sample when interpreting current swap rates. Old occupied swap is not evidence of current thrashing.
3. Follow `infra/README.md`: verify the dated cloud image checksum, provide a public SSH key, initialize an external local backend, review the plan, and apply only lab-owned resources. Back up state outside the checkout and guest. Never commit plans/state, and do not apply concurrently.
4. Confirm SSH to `vm_ip`, cloud-init completion, root disk expansion and a second Terraform plan with no changes. Defaults: 2 vCPU, 3072 MiB RAM, 25 GiB root disk.
5. Publish each application release once following `app/README.md`. Confirm the package is public and anonymous pulls work. Pin the published v1 digest in `gitops/deployment.yaml`; keep both release tags available for rebuilds.
6. Follow `bootstrap/README.md` to install the pinned K3s/Argo CD and apply the restricted project/application. Run kubectl inside the VM with its protected K3s kubeconfig; do not merge it with a production context.
7. Wait for node Ready, required pods ready and Argo application Synced/Healthy. Open the loopback-only tunnel below and check the response. Repeat host measurements and existing-service checks.

## Access and traffic path

Replace `<host>` with an existing SSH alias or host and `<VM_IP>` with Terraform output. No router, Caddy, Pi-hole or VPN configuration changes are required.

```sh
ssh -N -L 127.0.0.1:8081:<VM_IP>:80 <host>
curl --fail -H 'Host: gitops-lab.test' http://127.0.0.1:8081/
```

Path: workstation loopback → SSH connection terminating on host → VM Traefik :80 → Ingress host/path match → ClusterIP Service :80 → non-root application Pod :8080. The host's own port 80 is not used by this forwarding destination.

For Argo CD, use the component README's VM-loopback kubectl port-forward plus a jump-host SSH tunnel. Keep TLS, and retrieve the initial admin password privately; do not copy it into evidence or Git. Never expose the UI/API on public or host-wide listeners.

The lab uses its own `192.168.250.0/24` NAT network (recheck conflicts before every apply). DNS is disabled **only on this libvirt network** to avoid an existing wildcard DNS listener; DHCP remains enabled and cloud-init supplies guest resolvers. Kubernetes defaults are Pod `10.42.0.0/16` and Service `10.43.0.0/16`.

## Acceptance procedure

Save timestamped output privately; publish only sanitized summaries and commit IDs.

| Exercise | Evidence required |
|---|---|
| Initial v1 | Synced/Healthy, ready rollout, HTTP 200 containing `gitops-lab v1` |
| Push v2 | Pinned v2 commit pushed; automatic reconciliation and HTTP v2 without manual kubectl deployment |
| Drift | Scale Deployment manually; selfHeal restores `spec.replicas: 1` from Git |
| Broken image | Commit a nonexistent **tag without an existing digest**, capture pod description/events and Argo status |
| Recovery | `git revert` the broken commit; verify rollout, Argo status and HTTP v2 |
| Bootstrap repeat | Rerun bootstrap; versions unchanged, no unintended reinstall |
| Graceful restart | `virsh -c qemu:///system shutdown gitops-lab`, wait for shut off, start and verify recovery |
| Clean-disk rebuild | Reviewed destroy/apply recreates writable root disk and seed; bootstrap deploys expected Git version without restoring guest cluster data |
| Full cleanup | Reviewed destroy plan only lab-owned resources; afterward no lab domain, disk/seed/base volume, pool or NAT network remains |
| Final recreation | Reapply and bootstrap from clean disk; leave healthy v2 running after safety checks |

An invalid tag may leave the old healthy pod serving traffic during RollingUpdate; HTTP availability does not imply successful rollout. Argo may show Progressing rather than immediately Degraded. Diagnose the actual state instead of asserting one predetermined failure label.

## Diagnostics and shutdown

- Host: `free -h`, `vmstat 1`, `docker stats --no-stream`, `df -h /`, libvirt domain/network/pool inventory. `scripts/preflight.py` is read-only, bounded, and includes these measurements.
- Guest: cloud-init status/logs, K3s service journal, `sudo k3s kubectl get nodes,pods -A`, deployment rollout status, pod descriptions, ordered events, Service endpoints and Traefik logs.
- Network: first verify host-to-VM SSH/HTTP, then Ingress Host header, then Service selectors/endpoints, then Pod readiness. Inspect Docker/libvirt forwarding interaction without flushing firewall rules or changing security controls.
- On sustained swap activity, OOM, or production slowdown, gracefully shut down the lab and record the evidence. Do not stop production services or silently reduce safeguards to force completion. Avoid concurrent Ollama inference while evaluating this constrained host.
- Routine stop/start is via the lab domain only. After a host reboot, inspect network inventory and explicitly start the inactive `gitops-lab` network before starting the VM; network autostart is disabled. A stopped VM can cause Terraform to propose restoring its configured running state; inspect that plan. Graceful shutdown is not destruction.
- v1/v2 are deliberately minimal, single-threaded demo servers: a stalled HTTP request can block probes. Keep them behind the isolated SSH access path; see `app/README.md` for this known review finding. Never store real private data in the VM destroyed by these exercises.

## State, recreation and cleanup

Use an explicit external backend path and external provider-data directory as described in `infra/README.md`, restrictive file permissions, one operator, and a separate backup outside the guest. Never back up live guest database files as a substitute for reconstruction from Git. Copying state alone onto the same physical disk is not disaster protection: keep an additional protected off-host copy. No changes to existing family backup schedules are part of this lab.

Before destroy, confirm backend identity, review the saved destroy plan and every resource name/path. After destroy, verify using libvirt inventory and the dedicated storage directory, and recheck existing service health/DNS. Keep state/backups until cleanup is verified. Do not delete unrelated or package-created default networks. Follow `infra/README.md` for the exact wrapper invocation.

## Observations and results — 2026-11-14

Raw evidence is stored privately outside this checkout; internal addresses, secrets, and detailed production inventory are not published here.

| Check | Observed result |
|---|---|
| Initial capacity | About 4.1 GiB available of 7.6 GiB RAM; 148 GiB SSD free; 1.5 GiB swap occupied |
| Initial 10-second vmstat | No sustained swapping: samples after the first were zero except one small swap-in sample; this does not prove peak-load safety |
| Ollama | Service active, no model loaded |
| Intentionally unused applications | Left stopped; no start/config changes made |
| Documentation discrepancy | Additional analytics containers are already running; resource baseline includes them |
| Approved host prerequisites | Installed QEMU/libvirt/image tooling; added operator to libvirt/kvm; system connection works; checksum-verified Terraform installed in user lab tooling |
| Package default network | Created inactive by package setup; not enabled or used by lab |
| Post-prerequisite health | Existing dashboard, photo service, media service and password manager HTTP 200; split-DNS lookup resolves; no production configuration changes |
| Post-prerequisite capacity | About 4.1 GiB available; short follow-up samples had zero current swap activity |
| Application unit tests | 15 passed locally and in the v1 publication workflow |
| v1 image build/push | Successful GitHub-hosted run [43615319026](https://github.com/jgerchev/gitops-lab/actions/runs/43615319026) |
| v2 image build/push | Successful GitHub-hosted run [43615417852](https://github.com/jgerchev/gitops-lab/actions/runs/43615417852) |
| Public registry access | User changed package to public; anonymous GET of v1/v2 OCI indexes succeeded, header and independently computed SHA256 match workflow digests; v1 pinned in Git |
| Infrastructure validation | fmt, init, validate and nine safety tests passed; reviewed initial plan contained exactly seven lab creates |
| Provider diagnosis | First apply reported seed target `raw` versus libvirt-detected `iso`; corrected volume target to `iso`. Reviewed recovery plan replaced only tainted lab seed and created VM; apply succeeded |
| Initial guest reachability | SSH host key retrieved through authenticated host, neighbor MAC matched Terraform reservation and domain NIC; authenticated guest SSH later used for shutdown |
| Swap safety gate | Monitor observed 109 current samples before stopping; peak swap-in 7264 KiB/s, swap-out 27696 KiB/s. Five consecutive nonzero samples at 16:32:35–39 UTC triggered graceful shutdown request |
| Shutdown | ACPI request did not stop the VM promptly; authenticated guest `sudo systemctl poweroff` succeeded. Domain confirmed `shut off`; no forced power-off |
| After shutdown | About 4.4 GiB available, 1.8 GiB swap occupied; four current follow-up samples had zero swap I/O. SSD free about 146 GiB |
| Production services | During safety follow-up, dashboard/photo/media/password-manager endpoints returned HTTP 200 and DNS resolved; production containers remained running |
| State backup | Restricted host backup and additional mode-0600 off-host workstation copy, both outside Git/guest; local-backend state retained for safe cleanup |
| Bootstrap validation | Worker: 13 tests with downloaded artifacts passed plus ShellCheck. Coordinator: 10 static tests passed, 3 artifact-dependent tests skipped; no guest bootstrap executed |
| Read-only review | No bootstrap blocker found; explicit network startup after host reboot documented. Single-threaded HTTP demo limitation documented without overwriting immutable releases |
| Kubernetes, GitOps and lifecycle tests | NOT RUN: bootstrap/repeat, Synced/Healthy, ingress HTTP, v2 reconciliation, drift, broken rollout/revert, successful restart, clean rebuild, full cleanup and final running v2 |

No Immich peak-processing measurement has been performed yet. This sample establishes a failed operational safety gate, not a definitive diagnosis of swap cause or proof that a memory upgrade is the only solution. Do not silently lower VM memory or stop production services. Review host workload/swap behavior and agree on a safe retry before resuming.

Lab domain, dedicated network/pool and volumes remain Terraform-managed; the VM is off and no cluster exists. The requested final running-v2 state and cleanup demonstration were not reached because safety takes priority. The full assignment is not complete until the live acceptance results replace the pending entries above.

### Follow-up memory inspection (VM kept off)

- Libvirt XML confirms both configured and current guest allocation are exactly 3145728 KiB (3 GiB); QEMU overhead is additional. No per-QEMU RSS/cgroup sample was captured while it ran, so actual guest/process consumption cannot be reconstructed from this setting.
- Journal records VM process start at **16:32:35 UTC** and termination at **16:33:54 UTC**. The largest monitor swap bursts were **16:31:07–09 UTC**, before VM startup. They therefore cannot be attributed to running guest memory; infrastructure work and existing workload were concurrent, and the exact cause is unproven.
- The monitor trigger was the **first five seconds of VM startup**, with `(si,so)` KiB/s of `(12,0), (28,0), (0,16), (12,52), (0,464)`. Its consecutive-nonzero rule is intentionally conservative but does not distinguish tiny boot-time reclaim from harmful thrashing. No threshold was changed and no retry performed.
- Fresh 60-second VM-off sample: approximately **4.4 GiB MemAvailable**, **1.8 GiB occupied swap**, **no swap-out**, and occasional small swap-ins (largest 220 KiB/s). Memory-pressure stall averages were low (full avg60 approximately 0.26% at the end), not evidence of ongoing severe host thrashing.
- Existing container swap includes approximately 327 MiB for home automation, 274 MiB for the photo database, 170 MiB for the photo server and 158 MiB for the media server. These are current stored pages, not rates or proof of current problems; cgroup RAM includes cache and process RSS may double-count shared pages.
- Existing analytics containers have historical 512 MiB cgroup-limit hits, with no OOM-kill events in the inspected counters. Their lifetime counters and historical memory peaks have no timing information: they do not establish the cause of this run's swap bursts. No kernel OOM-kill messages were found in the inspected lab-session time window.
- Host swappiness is **60**; transparent huge pages use **madvise**. The actual swap file is `/swap.img`, unlike older documentation. No sysctl, swap, service, container-limit or production configuration changes were made.

Conclusion: **no evidence that the VM exceeded its planned guest allocation, and no demonstrated ongoing thrashing while off**. Current evidence does not prove safe operation with K3s/Argo CD or peak production load. A future explicitly agreed boot-only retry should capture per-QEMU/cgroup memory, MemAvailable, pressure stalls and swap rates together; keep existing safety restrictions until an appropriate measurement window/stop criterion is agreed.

### Authorized boot-only retry — VM now running

The user requested startup after the inspection. No Kubernetes installation,
host tuning, production changes, or resource-size changes were made.

- VM started at approximately 16:41:58 UTC. Initial telemetry incorrectly looked for memory counters in libvirt's emulator cgroup leaf; counters actually live in its parent. The monitor requested a precautionary ACPI shutdown on this collection error (not pressure), but the VM remained running. The corrected collector attached to the same process without another restart.
- Corrected observation: **120 samples, 16:42:32–16:44:32 UTC**. Stop criteria announced before startup: 10 consecutive swap-I/O samples, five low-memory samples below 512 MiB available, five samples with full memory stalls above 5%, or repeated production HTTP failure. No criterion triggered. These are experiment-specific observation gates, not a blanket production-capacity guarantee; the original repository monitor retains its earlier five-sample rule.
- QEMU RSS: approximately **744 MiB**, stable; VM cgroup memory charge approximately **814–835 MiB**, including cache/overhead; **zero process and cgroup swap** throughout.
- Host MemAvailable: **3.66–3.72 GiB**. Host swap activity was brief: longest nonzero streak **two samples**, max swap-in 63.8 KiB/s, max swap-out 1183.9 KiB/s. Largest one-interval full-memory stall fraction was 2.327%, not sustained.
- All **16 production health checks returned HTTP 200** across the four baseline endpoints.
- Authenticated guest SSH: cloud-init `done`, no errors/recoverable errors; guest used memory approximately **428 MiB**, available **2.4 GiB**; root filesystem grew to approximately **24 GiB**, with **22 GiB free**. Guest K3s service inactive/not installed.

The guest is left **running** as requested. This supersedes the earlier off-state status, but does not validate K3s/Argo memory usage, ingress, or peak Immich workloads. Full remaining acceptance tests are still pending.

### Bootstrap attempt — stopped before Kubernetes readiness

After the user explicitly requested installation, the coordinator confirmed
Terraform **No changes**, clean cloud-init status, working guest SSH, no loaded
local inference model, and healthy production endpoints. Both release artifacts
passed their pinned SHA256 checks. The bootstrap installed K3s binary/config and
enabled `k3s.service`, then the existing announced swap criterion triggered.

- Host observation: 20 samples, approximately **20:43:30–20:43:49 UTC**. Ten consecutive samples with nonzero swap I/O triggered a graceful shutdown request; guest SSH closed and bootstrap exited 255 with `Job for k3s.service canceled`.
- Minimum sampled host available RAM was about **3.15 GiB**. Peak sampled swap-in was **1050.6 KiB/s**, swap-out **15763.8 KiB/s**. Full-memory stalls peaked at **11.56% for one interval**, not five consecutive high-stall intervals.
- QEMU RSS grew to approximately **1.07 GiB**; process swap was approximately **87 MiB** at the last sample. Some QEMU pages were already swapped before bootstrap. This was a conservative swap-gate stop, **not proven total RAM exhaustion, an OOM, or a demonstrated production outage**.
- VM confirmed **shut off**. Follow-up: approximately **4.2 GiB** available host RAM, **1.9 GiB** occupied swap; nine current samples showed no swap-out and only one small swap-in. All four production endpoints returned HTTP 200, DNS resolved, and no kernel OOM-kill entry appeared in the inspected attempt window.
- K3s API/node/Traefik readiness was **not reached or verified**. Argo CD installation, Application creation, ingress validation and bootstrap repeatability were **not reached**. The enabled K3s service remains on the persistent lab disk; starting the VM again will automatically attempt K3s startup.

No automatic retry, VM resizing, swap/sysctl tuning, or production changes were
made. Resume only after reviewing the swap criterion and agreeing on the next
measurement approach; keep the protected Terraform state and partial guest for
diagnosis. Raw attempt/monitor logs remain private outside this repository.
