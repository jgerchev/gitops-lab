output "vm_name" {
  description = "Lab libvirt domain name."
  value       = libvirt_domain.lab.name
}

output "vm_ip" {
  description = "Reserved DHCP address; not a readiness/SSH reachability assertion."
  value       = local.vm_ip
}
