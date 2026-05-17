# Kata Container Configuration for TEE Inference Nodes

## Purpose

Provides Open Policy Agent (OPA) policy and Kata Containers runtime configuration to enforce runtime tampering prevention on TEE inference nodes. The OPA policy blocks dangerous runtime operations like `ExecProcessRequest` and `SignalProcessRequest`, allowing only safe container lifecycle operations (create, start, stop, remove).

## Prerequisites

- **Kata Containers**: Installed and functional on the host
- **CVM Host**: Either SEV-SNP (AMD) or TDX (Intel) confidential VM
- **Root/sudo access**: Required to modify system configuration files

## How to Apply

1. Copy the OPA policy to the system:
   ```bash
   sudo cp policy.rego /etc/kata-containers/policy.rego
   sudo chmod 644 /etc/kata-containers/policy.rego
   ```

2. Merge the Kata runtime configuration:
   ```bash
   sudo cp kata-config.toml /tmp/kata-config.toml
   # Manually merge the [hypervisor.qemu] and [agent.kata] sections into
   # /etc/kata-containers/configuration.toml, or replace if using stock config
   ```

3. Restart Kata Containers runtime:
   ```bash
   sudo systemctl restart kata-containers
   ```

## How to Verify

Attempt to execute a process inside a running Kata container:

```bash
kubectl exec -it <pod-name> -- /bin/bash
```

**Expected result**: The exec request should be denied by the OPA policy with an error indicating policy violation.

## Reference

See [docs/04-anti-cheat.md](../docs/04-anti-cheat.md) section 10a for full context on anti-cheat mechanisms and Kata Containers integration.

## Files

- `policy.rego` — OPA policy denying exec and signal operations
- `kata-config.toml` — Runtime configuration for confidential guests with DM-Verity
- `README.md` — This file
