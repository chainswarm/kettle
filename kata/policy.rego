# OPA policy for Kata Containers — blocks runtime tampering
#
# With default allow = false, only explicitly allowed actions pass.
# ExecProcessRequest and SignalProcessRequest are NOT in the allow
# list, so they are implicitly denied.
package kata

default allow = false

# Allow container lifecycle operations only
allow {
    input.action == "CreateContainerRequest"
}
allow {
    input.action == "StartContainerRequest"
}
allow {
    input.action == "StopContainerRequest"
}
allow {
    input.action == "RemoveContainerRequest"
}

# ExecProcessRequest — NOT allowed (no rule → denied by default)
# SignalProcessRequest — NOT allowed (no rule → denied by default)
