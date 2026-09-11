# Feature082 final process observation plan

This is a read-only closure procedure written after launch. It changes no product, helper,
test, input, registered condition or existing evidence. Run it after the native campaign and
both slots have durable terminal evidence; reconcile the independent082 final audit separately.
No process observation authorizes a receipt or score.

## Identities already observed

Both initial observations bind manifest
`880761221b0ac2bb11acaffac2dbb8312171ae91adcc6da5ffd06763d2546bdb`.

| Role | PID | PPID | PGID |
|---|---:|---:|---:|
| Dispatcher | 88086 | 1 | 88086 |
| Slot1 worker | 88266 | 88086 | 88266 |
| Slot2 worker | 88267 | 88086 | 88267 |
| Slot1 subject | 88272 | 88266 | 88272 |
| Slot2 subject | 88273 | 88267 | 88273 |
| Observed slot1 HTTP worker | 88405 | 88272 | 88272 |
| Observed slot2 HTTP worker | 88860 | 88273 | 88273 |

The last two PIDs describe the workers visible at04:33:10UTC, not all workers ever created.
`http_transport.exchange()` does not create a new session/group: its worker inherits the
subject PGID. Its parent owns a lifeline writer; EOF exits the worker, and normal transport
cleanup kills/reaps its one owned PID. Final observation must still check the visible result.

The existing watcher derives known IDs from native markers and filters known PID/PGID members
plus immediate children. Those native subject markers explicitly contain null child IDs, so
the watcher's initial known sets contain only88086/88266/88267. Its empty final list alone
cannot rule out an orphan HTTP worker in subject group88272 or88273. Union all saved progress
rows and the richer initial descendant observation before checking final liveness.

The native harness gets a separate process group. Its extractor/evaluator also use
`start_new_session=True`, with cwd under the two registered private case roots, outside this
campaign directory. Capture newly visible harness/descendant groups while observable. At the
end, check both private case roots as possible associations; shared historical input paths
alone do not uniquely establish082 ownership.

## Final read-only command

From the repository root, the command below prints only a projected JSON observation. It reads
numeric process metadata, current working directories and argv for the resulting candidates;
it never reads process environments, transcripts, candidate contents or credentials. Preserve
stdout as a **new** timestamped postrun JSON file, without overwriting any observation. An
inspection failure raises or appears as an explicit visibility limitation, never as clean.

```sh
.venv/bin/python -B - <<'PY'
import datetime as dt
import hashlib
import json
import shlex
import subprocess
from pathlib import Path

repo = Path.cwd().resolve()
feature = repo / 'specs/082-http-deadline-measurement'
manifest_path = feature / 'measurement/manifest.json'
raw = manifest_path.read_bytes()
digest = hashlib.sha256(raw).hexdigest()
assert digest == '880761221b0ac2bb11acaffac2dbb8312171ae91adcc6da5ffd06763d2546bdb'
manifest = json.loads(raw)
campaign = repo / '.lunar' / manifest['campaign_id']
assert (campaign / 'terminated.json').is_file()
assert all((campaign / f'slot-{n:03d}-terminated.json').is_file() for n in (1, 2))
known_pids, known_pgids = set(), set()

def collect(value):
    if isinstance(value, dict):
        for key, item in value.items():
            target = known_pids if key in {'pid', 'ppid', 'dispatcher_pid', 'worker_pid', 'child_pid'} else (
                known_pgids if key in {'pgid', 'dispatcher_pgid', 'worker_pgid', 'child_pgid'} else None)
            if target is not None and type(item) is int and item > 1:
                target.add(item)
            if key in {'known_pids', 'known_pgids'} and isinstance(item, list):
                (known_pids if key == 'known_pids' else known_pgids).update(
                    n for n in item if type(n) is int and n > 1)
            collect(item)
    elif isinstance(value, list):
        for item in value:
            collect(item)

evidence = [feature / 'measurement' / name for name in (
    'initial-descendant-processes.json', 'initial-process-observation.json', 'launch-observation.json')]
evidence += sorted((feature / 'postrun/progress').glob('*.json'))
evidence += sorted(campaign.glob('*started.json'))
evidence += sorted(campaign.glob('slots/*/*started.json'))
for path in evidence:
    value = json.loads(path.read_bytes())
    assert value.get('manifest_sha256') == digest
    collect(value)
roots = [campaign] + [repo / case['private_root_rel'] for case in manifest['cases'].values()]
started = dt.datetime.now(dt.timezone.utc).isoformat()
cwd_result = subprocess.run(['/usr/sbin/lsof', '-nP', '-d', 'cwd', '-Fpn'],
                            capture_output=True, text=True, timeout=20)
cwd_hits, pid = {}, None
for line in cwd_result.stdout.splitlines():
    if line.startswith('p') and line[1:].isdigit():
        pid = int(line[1:])
    elif line.startswith('n/') and pid is not None:
        path = Path(line[1:])
        for index, root in enumerate(roots):
            if path == root or root in path.parents:
                cwd_hits[pid] = 'campaign' if index == 0 else 'shared_private_case'
ps = subprocess.check_output(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,stat=,lstart='],
                             text=True, timeout=10)
table = {}
for line in ps.splitlines():
    p, parent, group, state, start = line.split(None, 4)
    table[int(p)] = dict(pid=int(p), ppid=int(parent), pgid=int(group), state=state, lstart=start)
selected = {p for p, row in table.items()
            if p in known_pids or row['pgid'] in known_pgids or p in cwd_hits}
while True:
    grown = selected | {p for p, row in table.items()
                        if row['ppid'] in selected or row['ppid'] in known_pids}
    if grown == selected:
        break
    selected = grown
rows = []
helper = str(repo / 'src/famou/http_transport.py')
for p in sorted(selected):
    result = subprocess.run(['/bin/ps', '-p', str(p), '-o', 'command='],
                            capture_output=True, text=True, timeout=10)
    try:
        tokens = shlex.split(result.stdout.strip()) if result.returncode == 0 else []
    except ValueError:
        tokens = []
    rows.append({**table[p], 'cwd_scope': cwd_hits.get(p),
                 'argv_observed': bool(tokens),
                 'http_helper_argv': helper in tokens and all(flag in tokens for flag in ('-I', '-S', '-B')),
                 'campaign_path_in_argv': any(t == str(campaign) or t.startswith(str(campaign) + '/')
                                              for t in tokens)})
print(json.dumps({'kind': 'feature082_final_scoped_process_observation',
                  'manifest_sha256': digest, 'started_utc': started,
                  'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'known_pids': sorted(known_pids), 'known_pgids': sorted(known_pgids),
                  'visible_candidates': rows, 'cwd_scan_returncode': cwd_result.returncode,
                  'cwd_scan_stderr_present': bool(cwd_result.stderr),
                  'point_in_time_only': True, 'process_environments_read': False,
                  'raw_argv_saved': False, 'model_calls': 0}, indent=2))
PY
```

## Interpretation and follow-through

- Check that the native final audit is complete and hashes reconcile independently. Preserve the
  watcher completion/exit result separately; the watcher is an observer, not a campaign worker.
- A nonempty list includes possible relations, zombies and possible PID/group reuse. It is not
  an instruction to signal anything. Inspect the projected relationship and scoped identities;
  the initial observations lack process start times, so retain ambiguity when ownership cannot
  be established. Never treat an unrelated reused PID as proof of an082 leak.
- If empty and inspection succeeded, state: **no visible process remained in the recorded
  PID/groups, their visible descendant closure, or the checked cwd associations at that time**.
  Do not claim a global proof of no residual process or stopped remote generation/billing.
- lsof permissions, processes exiting between snapshots, a missed short-lived harness and
  descendants that changed session/parent/cwd before observation limit visibility. Private-case
  cwd can refer to another campaign. Retain these limits rather than repairing missing IDs.
- If a candidate remains or tools report an observation failure, a second read-only snapshot
  may resolve exit/reuse races. Save a distinct file and report the unresolved state if it does
  not clear. Do not change frozen code, restart slots, or send signals as part of this procedure.

The command was reviewed against the recorded schema and current frozen process-launch code.
It has not been executed as a final observation while the campaign is running.
