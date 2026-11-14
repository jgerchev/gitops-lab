variable "ssh_public_key" {
  description = "One OpenSSH public key for lab; never pass a private key."
  type        = string
  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]+( [^\\r\\n]*)?$", trimspace(var.ssh_public_key)))
    error_message = "Supply a single OpenSSH public key, not a private key or filename."
  }
}

variable "image_path" {
  description = "Absolute external path to the verified, unmodified Ubuntu image."
  type        = string
  validation {
    condition     = startswith(var.image_path, "/")
    error_message = "image_path must be absolute. Use scripts/fetch-image.py."
  }
}
