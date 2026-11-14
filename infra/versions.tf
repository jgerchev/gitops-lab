terraform {
  required_version = "= 1.17.2"
  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "= 0.9.9"
    }
  }
  # Deliberately partial: scripts/tf.py supplies absolute external paths.
  backend "local" {}
}

provider "libvirt" {
  uri = "qemu:///system"
}
