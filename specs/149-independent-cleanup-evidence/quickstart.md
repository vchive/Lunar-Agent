# Quickstart

Build a cleanup receipt from a supervisor's already-collected identities and probe result, then
parse it again with the launch and result digests. The parser performs no process access and no
filesystem mutation. Use the native execution inspector for retained `cleanup.json`; do not
construct a completion descriptor by hand or copy an attempt directory.
