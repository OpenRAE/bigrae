resource "google_compute_network" "range" {
  name                    = "${var.name_prefix}-range"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_route" "range_private_googleapis" {
  name             = "${var.name_prefix}-range-private-googleapis"
  project          = var.project_id
  network          = google_compute_network.range.name
  description      = "Private Google Access: route the private.googleapis.com VIP over Google's internal fabric for range guests."
  dest_range       = "199.36.153.8/30"
  next_hop_gateway = "default-internet-gateway"
  priority         = 1000
}

resource "google_dns_managed_zone" "range_private_googleapis" {
  name        = "${var.name_prefix}-range-googleapis"
  project     = var.project_id
  dns_name    = "googleapis.com."
  description = "Private Google Access: resolve *.googleapis.com to the private.googleapis.com VIP for range guests."

  visibility = "private"

  private_visibility_config {
    networks {
      network_url = google_compute_network.range.id
    }
  }
}

resource "google_dns_record_set" "range_private_googleapis_a" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.range_private_googleapis.name
  name         = "private.googleapis.com."
  type         = "A"
  ttl          = 300
  rrdatas      = ["199.36.153.8", "199.36.153.9", "199.36.153.10", "199.36.153.11"]
}

resource "google_dns_record_set" "range_private_googleapis_wildcard" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.range_private_googleapis.name
  name         = "*.googleapis.com."
  type         = "CNAME"
  ttl          = 300
  rrdatas      = ["private.googleapis.com."]
}

# PLAT-238 / ADR-026-R6: the shared range NAT no longer enrolls every subnet
# (`ALL_SUBNETWORKS_ALL_IP_RANGES`). That posture is incompatible with a per-range
# `none` (zero-egress) subnet, because a firewall deny does not remove NAT
# enrollment. Range egress is now range-owned: the provisioner creates a
# range-scoped Cloud Router + NAT for each non-`none` range and creates none for a
# zero-egress range. This shared router/NAT is retained only as a controlled
# migration bridge -- it enrolls exactly the subnet self-links listed in
# `shared_range_nat_subnetwork_self_links`. That list defaults empty, and the
# whole router/address/NAT is then NOT created at all (a `LIST_OF_SUBNETWORKS`
# Cloud NAT with zero subnetworks is rejected by GCP, so the steady state must
# omit it rather than create an empty one). During a cutover an operator may
# temporarily list existing pre-migration range subnets here to preserve their
# egress until they are drained/rebuilt onto per-range NAT; range jobs never
# mutate this object (no concurrent patching).
locals {
  # A range subnet self-link is
  # https://www.googleapis.com/compute/v1/projects/<p>/regions/<region>/subnetworks/<name>.
  # Cloud NAT is regional, so group the migration-bridge self-links by their own
  # region: the primary-region router enrolls only primary-region subnets, and each
  # additional pooled region gets its own bridge NAT below. Enrollment is always an
  # explicit LIST_OF_SUBNETWORKS, never ALL_SUBNETWORKS (that would NAT a
  # zero-egress `none` range -- ADR-026-R6).
  shared_range_nat_by_region = {
    for region in distinct([
      for self_link in var.shared_range_nat_subnetwork_self_links :
      regex("/regions/([^/]+)/subnetworks/", self_link)[0]
      ]) : region => [
      for self_link in var.shared_range_nat_subnetwork_self_links :
      self_link if regex("/regions/([^/]+)/subnetworks/", self_link)[0] == region
    ]
  }
  shared_range_nat_primary_subnets = lookup(local.shared_range_nat_by_region, var.region, [])
  shared_range_nat_enabled         = length(local.shared_range_nat_primary_subnets) > 0
}

resource "google_compute_router" "range_nat" {
  count   = local.shared_range_nat_enabled ? 1 : 0
  name    = "${var.name_prefix}-range-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.range.id
}

resource "google_compute_address" "range_nat" {
  count        = local.shared_range_nat_enabled ? 1 : 0
  name         = "${var.name_prefix}-range-nat-egress"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "range_nat" {
  count                              = local.shared_range_nat_enabled ? 1 : 0
  name                               = "${var.name_prefix}-range-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.range_nat[0].name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.range_nat[0].self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  dynamic "subnetwork" {
    for_each = toset(local.shared_range_nat_primary_subnets)
    content {
      name                    = subnetwork.value
      source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
    }
  }

  # #2535: range egress NAT logging follows settings.range_telemetry.nat_logs.
  log_config {
    enable = var.nat_logs.enabled
    filter = var.nat_logs.filter
  }
}

# #2029 multi-region range placement: a range cell placed in a region other than
# the primary control-plane region (via RANGE_NETWORK_ZONES) reaches egress through
# its own region-aware per-range Cloud NAT (provisioner-owned, ADR-026-R6). This
# shared extra-region router/NAT is only the migration bridge for pre-migration
# subnets that live in an additional pooled region: like the primary-region bridge
# it enrolls exactly the listed subnets via LIST_OF_SUBNETWORKS -- never
# ALL_SUBNETWORKS, which would also NAT a zero-egress `none` range. A pooled region
# with no listed subnets gets no shared NAT (empty pool / empty list -> no extra
# resources, single-region unchanged), and a listed subnet outside the operator's
# declared zone pool is not bridged.
locals {
  range_pool_regions = toset([for z in var.range_network_zones : replace(z, "/-[a-z]$/", "")])
  shared_range_nat_extra_regions = {
    for region, subnets in local.shared_range_nat_by_region :
    region => subnets
    if region != var.region && contains(local.range_pool_regions, region)
  }
}

resource "google_compute_router" "range_nat_extra" {
  for_each = local.shared_range_nat_extra_regions
  name     = "${var.name_prefix}-range-nat-${each.key}"
  project  = var.project_id
  region   = each.key
  network  = google_compute_network.range.id
}

resource "google_compute_address" "range_nat_extra" {
  for_each     = local.shared_range_nat_extra_regions
  name         = "${var.name_prefix}-range-nat-egress-${each.key}"
  project      = var.project_id
  region       = each.key
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "range_nat_extra" {
  for_each                           = local.shared_range_nat_extra_regions
  name                               = "${var.name_prefix}-range-nat-${each.key}"
  project                            = var.project_id
  region                             = each.key
  router                             = google_compute_router.range_nat_extra[each.key].name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.range_nat_extra[each.key].self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  dynamic "subnetwork" {
    for_each = toset(each.value)
    content {
      name                    = subnetwork.value
      source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
    }
  }

  log_config {
    enable = var.nat_logs.enabled
    filter = var.nat_logs.filter
  }
}

resource "google_compute_firewall" "range_deny_ingress_all" {
  name        = "${var.name_prefix}-range-deny-ingress-all"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: range VPC ingress is denied by default; explicit allow rules ride higher precedence."
  direction   = "INGRESS"
  priority    = 65000

  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

resource "google_compute_firewall" "range_allow_platform_provisioner" {
  name        = "${var.name_prefix}-range-allow-platform-provisioner"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: provisioner-pod traffic (dedicated GKE pod range) into range VMs on documented ports only."
  direction   = "INGRESS"
  priority    = 1000

  source_ranges = [var.gke_provisioner_pods_cidr]

  allow {
    protocol = "tcp"
    ports    = [for p in var.range_provisioner_ports : tostring(p)]
  }
}

resource "google_compute_firewall" "range_allow_operator_admin_ssh" {
  count = length(var.operator_admin_cidrs) > 0 ? 1 : 0

  name        = "${var.name_prefix}-range-allow-operator-admin-ssh"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: break-glass direct SSH into range VMs from the operator-admin CIDR allowlist (not IAP)."
  direction   = "INGRESS"
  priority    = 800

  source_ranges = var.operator_admin_cidrs

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "terraform_data" "range_egress_invariant" {
  lifecycle {
    precondition {
      condition = (
        (var.range_egress_mode == "status-quo" && length(var.range_egress_allowed_cidrs) == 0)
        || (var.range_egress_mode == "deny-all" && length(var.range_egress_allowed_cidrs) == 0)
        || (var.range_egress_mode == "allowlist" && length(var.range_egress_allowed_cidrs) > 0)
      )
      error_message = "PLAT-220: range_egress_mode='allowlist' requires a non-empty range_egress_allowed_cidrs; range_egress_mode='deny-all' or 'status-quo' must carry an empty list. The public RangeEgressPolicy contract (shifter/installation/range_egress.py) enforces this; this precondition mirrors it for direct Terraform use."
    }
  }
}

resource "google_compute_firewall" "range_egress_deny_all" {
  count = var.range_egress_mode == "status-quo" ? 0 : 1

  name        = "${var.name_prefix}-range-egress-deny-all"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "PLAT-220: range egress is policy-driven. Low-precedence deny enforces fail-closed when the operator selects deny-all or allowlist; the allowlist rule rides higher precedence."
  direction   = "EGRESS"
  priority    = 65534

  destination_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

resource "google_compute_firewall" "range_egress_allow_allowlist" {
  count = var.range_egress_mode == "allowlist" && length(var.range_egress_allowed_cidrs) > 0 ? 1 : 0

  name        = "${var.name_prefix}-range-egress-allow-allowlist"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "PLAT-220: range egress allowlist (HTTPS to operator-declared CIDRs). Higher precedence than the deny-all base so the named destinations actually reach the internet."
  direction   = "EGRESS"
  priority    = 1000

  destination_ranges = var.range_egress_allowed_cidrs

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

# Shared-guest firewall layout. These fixed rules replace the per-range access,
# egress and deny rules, so a range creates only its isolation rule. The tag
# value must match SHARED_GUEST_TAG in shifter/engine/provisioner/gcp_range_cell_firewall.py.
locals {
  shared_guest_tag = "shifter-range-guest"
}

resource "terraform_data" "shared_guest_firewall_inputs" {
  count = var.shared_guest_firewalls ? 1 : 0

  lifecycle {
    precondition {
      condition     = can(cidrhost(var.range_network_cidr, 0)) && length(var.access_network_cidrs) > 0
      error_message = "shared_guest_firewalls needs range_network_cidr and at least one access_network_cidrs entry."
    }
  }
}

resource "google_compute_firewall" "shared_guest_access" {
  count = var.shared_guest_firewalls ? 1 : 0

  name          = "${var.name_prefix}-range-guest-access"
  project       = var.project_id
  network       = google_compute_network.range.name
  description   = "Participant SSH and RDP from the access workloads (portal, guacd) to every shared-guest range host."
  direction     = "INGRESS"
  priority      = 900
  target_tags   = [local.shared_guest_tag]
  source_ranges = var.access_network_cidrs

  allow {
    protocol = "tcp"
    ports    = ["22", "3389"]
  }
}

resource "google_compute_firewall" "shared_guest_egress_internal" {
  count = var.shared_guest_firewalls ? 1 : 0

  name               = "${var.name_prefix}-range-guest-egress-internal"
  project            = var.project_id
  network            = google_compute_network.range.name
  description        = "Guest egress inside the range network. Each range's isolation rule admits ingress only from its own subnet."
  direction          = "EGRESS"
  priority           = 1000
  target_tags        = [local.shared_guest_tag]
  destination_ranges = [var.range_network_cidr]

  allow {
    protocol = "all"
  }
}

resource "google_compute_firewall" "shared_guest_egress_deny" {
  count = var.shared_guest_firewalls ? 1 : 0

  name               = "${var.name_prefix}-range-guest-egress-deny"
  project            = var.project_id
  network            = google_compute_network.range.name
  description        = "Default guest egress deny below every allow."
  direction          = "EGRESS"
  priority           = 65534
  target_tags        = [local.shared_guest_tag]
  destination_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

resource "google_compute_firewall" "shared_guest_egress_googleapis" {
  count = var.shared_guest_firewalls && var.private_google_access ? 1 : 0

  name               = "${var.name_prefix}-range-guest-egress-googleapis"
  project            = var.project_id
  network            = google_compute_network.range.name
  description        = "Private Google Access TLS route through the guest egress deny. It supplies no guest credentials."
  direction          = "EGRESS"
  priority           = 1100
  target_tags        = [local.shared_guest_tag]
  destination_ranges = ["199.36.153.8/30"]

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}
