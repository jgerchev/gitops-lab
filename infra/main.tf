locals {
  name         = "gitops-lab"
  vm_ip        = "192.168.250.10"
  mac          = "52:54:00:47:4f:50"
  image_sha256 = "04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94"
}

resource "libvirt_pool" "lab" {
  name = local.name
  type = "dir"
  target = {
    path = "/var/lib/libvirt/gitops-lab"
  }
}

resource "libvirt_network" "lab" {
  name      = local.name
  autostart = false
  bridge    = { name = "virbr-gitops" }
  forward   = { mode = "nat" }
  # 0.9.9 uses the libvirt XML spelling, not dns.enabled. Avoid port 53:
  # Pi-hole owns wildcard TCP/UDP 53; DHCP remains available via dnsmasq.
  dns = { enable = "no" }
  ips = [{
    address = "192.168.250.1"
    prefix  = 24
    family  = "ipv4"
    dhcp = {
      # Reservation only: no address pool for unrelated guests.
      hosts = [{ mac = local.mac, ip = local.vm_ip, name = local.name }]
    }
  }]
}

resource "libvirt_volume" "base" {
  name   = "gitops-lab-ubuntu-24.04-20261017.qcow2"
  pool   = libvirt_pool.lab.name
  target = { format = { type = "qcow2" } }
  create = { content = { url = var.image_path } }
  lifecycle {
    precondition {
      condition     = try(filesha256(var.image_path) == local.image_sha256, false)
      error_message = "Missing/corrupt Ubuntu image; run scripts/fetch-image.py."
    }
  }
}

# A fresh overlay gives an actual 25 GiB virtual disk without overwriting its
# qcow2 header with the smaller source image's header during upload.
resource "libvirt_volume" "root" {
  name       = "gitops-lab-root.qcow2"
  pool       = libvirt_pool.lab.name
  capacity   = 25 * 1024 * 1024 * 1024
  allocation = 0
  target     = { format = { type = "qcow2" } }
  backing_store = {
    path   = libvirt_volume.base.path
    format = { type = "qcow2" }
  }
}

resource "libvirt_cloudinit_disk" "lab" {
  name = "gitops-lab-seed"
  meta_data = yamlencode({
    instance-id    = "gitops-lab-01"
    local-hostname = local.name
  })
  user_data = join("\n", ["#cloud-config", yamlencode({
    hostname         = local.name
    manage_etc_hosts = true
    disable_root     = true
    ssh_pwauth       = false
    users = [{
      name                = "lab"
      shell               = "/bin/bash"
      groups              = ["sudo"]
      sudo                = "ALL=(ALL) NOPASSWD:ALL"
      lock_passwd         = true
      ssh_authorized_keys = [trimspace(var.ssh_public_key)]
    }]
    growpart      = { mode = "auto", devices = ["/"], ignore_growroot_disabled = false }
    resize_rootfs = true
  })])
  network_config = yamlencode({
    version = 2
    ethernets = {
      lab = {
        match             = { macaddress = local.mac }
        "set-name"        = "ens3"
        dhcp4             = true
        dhcp6             = false
        "dhcp-identifier" = "mac"
        "dhcp4-overrides" = { "use-dns" = false }
        nameservers       = { addresses = ["1.1.1.1", "9.9.9.9"] }
      }
    }
  })
}

resource "libvirt_volume" "seed" {
  name = "gitops-lab-seed.iso"
  pool = libvirt_pool.lab.name
  # Libvirt identifies the uploaded cloud-init file as ISO, not raw.
  target = { format = { type = "iso" } }
  create = { content = { url = libvirt_cloudinit_disk.lab.path } }
}

resource "libvirt_domain" "lab" {
  name        = local.name
  type        = "kvm"
  memory      = 3072
  memory_unit = "MiB"
  vcpu        = 2
  running     = true
  autostart   = false
  cpu         = { mode = "host-model" }
  os = {
    type         = "hvm"
    type_arch    = "x86_64"
    type_machine = "q35"
    boot_devices = [{ dev = "hd" }]
  }
  features = { acpi = true }
  devices = {
    disks = [
      {
        device = "disk"
        driver = { name = "qemu", type = "qcow2" }
        source = { file = { file = libvirt_volume.root.path } }
        target = { dev = "vda", bus = "virtio" }
      },
      {
        device    = "cdrom"
        read_only = true
        driver    = { name = "qemu", type = "raw" }
        source    = { file = { file = libvirt_volume.seed.path } }
        target    = { dev = "sda", bus = "sata" }
      }
    ]
    interfaces = [{
      mac    = { address = local.mac }
      model  = { type = "virtio" }
      source = { network = { network = libvirt_network.lab.name } }
    }]
  }
}
