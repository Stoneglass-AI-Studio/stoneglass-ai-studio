# Scoped AppContainer prototype results

> Historical phase record. Current runtime/UI behavior and accepted offline scope
> are documented in [Stage 3](STAGE3_UI.md) and [Stage 3.1](OFFLINE_UI_ACCEPTANCE.md).
> Earlier unavailable features and security gates below describe that phase only.

**Outcome: prototype implemented; strict network-verification gate did not pass.**
No PyTorch, ROCm operator or SDXL/CLIP import probe was run inside the container.
No real checkpoint was loaded, no image generated and no model downloaded. The
production inference authorization gate and Generate button remain closed.
This result does not establish that ROCm is incompatible with AppContainer:
GPU testing was correctly withheld at the earlier network gate.

## Implementation and approved scope

`inference/windows_appcontainer.py` contains an explicit Windows-only primitive;
the application does not register or invoke it automatically. Provisioning was an
explicit development operation. One unique `Stoneglass.OfflineInference.Dev.*`
profile was created, with **zero capabilities**, including no network capabilities.
Its exact name/SID and staged paths are recorded in ignored private evidence.

A separate hash-verified Python 3.13.12/runtime/dependency copy was staged under
`.local-data/offline-sandbox/<run-id>/`. Disk preflight budgeted two staging copies
plus a 5 GiB reserve. The existing Python environments and reference application
were not copied as applications or changed; only required interpreter files,
the approved standalone dependency environment and Stoneglass worker code were
staged. No model/configuration bundle was copied. License notices present in the
installed runtime were retained; staging is not approval for binary redistribution.

The new staged root has a protected DACL for its owner, SYSTEM, administrators
and the specific AppContainer SID. Broad inherited user grants were removed from
this **new tree only**. The container gets read/execute on runtime/code and modify
on its writable cache/temp/output subtree, which has a low-integrity label.
Initial label application failed because the owner lacked `WRITE_OWNER`; this
was resolved by a temporary grant to that owner on the new writable root only,
applying the approved low label, then restoring its exact previous DACL. No
additional AppContainer capability or existing-resource permission was granted.

The native launcher:

- Validates a unique staging root, local paths and staged Python/script placement.
- Checks existing filtering services and absence of a profile loopback exemption.
- Uses `STARTUPINFOEX` with zero capabilities, an explicit three-pipe handle list
  and restricted child-process creation.
- Creates suspended, assigns a kill-on-close job with an active-process limit of
  one, then inspects the actual executable image, AppContainer SID, capability
  count, child mitigation and job membership **before resuming**.
- Owns bounded termination/reaping and pipe handles; failed cleanup retains
  ownership for retry. No PID guessing, global process termination or fallback
  to an unrestricted inference child is used.

The staged console `python.exe` exited with `0xC0000142` before the probe. The
staged headless `pythonw.exe` ran successfully with the same restrictions and
inherited pipe handles. This is an observed difference, not a confirmed diagnosis
of the console variant's loader failure. Python emitted a location-resolution
warning, although the reported executable/prefix remained within staging.

Microsoft's [AppContainer launch documentation](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
describes the token/security-capability approach. The profile/grants here are
limited to the approved development prototype; no global firewall rule, audit
policy, loopback exemption, driver or existing environment ACL was changed.

## Native observations

Tests used responders owned by the test controller on IPv4/IPv6 loopback and a
local DNS responder bound exclusively to `127.0.0.1:53`. If that port were occupied,
the test would stop rather than contact an unrelated resolver. DNS queries used a
random `.invalid.` test name and an explicit local server, with no forwarding.
Ordinary staged Python passed before and after the sealed run; the original
`.venv` Python also passed the same controlled network baseline.

| Check | Observed result | Assessment |
| --- | --- | --- |
| Token and image | AppContainer true, exact profile SID, zero capabilities, exact staged image | Verified |
| Child creation | Windows error 367, `ERROR_CHILD_PROCESS_BLOCKED` | Explicit OS denial |
| IPC | All three standard handles were pipes | Verified |
| Cache write | Owned test file written and removed | Allowed only in approved writable area |
| Runtime write and outside canary read | Python `EACCES` (errno 13) | Explicit filesystem denial |
| Native DNS query | Windows `ERROR_ACCESS_DENIED` (5) | Explicit OS denial; ordinary control received its NXDOMAIN response |
| IPv4/IPv6 TCP loopback | Python timeouts | Insufficient denial evidence |
| Direct native Winsock TCP | `WSAETIMEDOUT` (10060) | Insufficient denial evidence |
| Native WinHTTP | `ERROR_WINHTTP_TIMEOUT` (12002) | Insufficient denial evidence |
| IPv4/IPv6 UDP sends | `sendto` accepted data; controlled receivers got none | Consistent with drops, but not explicit denial proof |
| Controlled receiver counts during sealed run | Unchanged | No packets reached those receivers; not a general packet trace |
| Unrestricted controls after sealed run | TCP/UDP/HTTP/DNS still worked | Ordinary Python networking unaffected |

Do not describe accepted UDP sends as successful delivery, or quiet receivers as
proof that no traffic can leave through any interface. External/other-interface
coverage was not completed after this gate failed. Other applications were not
individually exercised; their configuration was untouched, and the independent
Python controls provide a bounded check rather than a claim about every app.

`NetworkIsolationDiagnoseConnectFailureAndGetInfo` did not attribute the loopback
failures to a missing capability, so it did not close the evidence gap. Existing
WFP diagnostic reads/event-enumerator creation returned access denied (5). No
event collection, tracing or security auditing was enabled to work around that.
Microsoft documents [WFP capability-drop events](https://learn.microsoft.com/en-us/windows/win32/api/fwpmtypes/ns-fwpmtypes-fwpm_net_event_capability_drop0)
as possible OS-level evidence, and [filter-origin diagnostics](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/filter-origin-documentation)
include AppContainer loopback blocking. Those sources do not substitute for a
captured event from this prototype.

The conservative evidence evaluator explicitly rejects timeouts, missing results
and successful send acceptance as access-denial proof. Production authorization
has not been changed to trust a profile name, environment flag or this report.

## Tests, evidence and remaining blocker

Native evidence and provisioning commands are in ignored
`.test-artifacts/appcontainer-prototype/`. They include profile/permission records,
process/token details, staging hashes, controlled baseline/receiver results,
diagnostic failures and the preservation audit. These machine-specific records
are not public source assets.

Automated tests use no actual model or GPU. They exercise the existing UI/service
suite, native structure sizes, namespace/path restrictions, strict token checks,
bounded/idempotent job cleanup, cleanup retry, and fail-closed network-evidence
assessment. **138/138 tests passed in offscreen Qt and 138/138 in native Windows
Qt** using `.venv-rocm`. Both `.venv-rocm` and `.venv` passed `pip check`.
Full results are recorded alongside native logs.
Unit tests never create another profile or change permissions.

The next step needs a separately reviewed way to obtain **actual OS filtering/drop
evidence scoped to this profile/process**, with suitable diagnostic access. The
current execution token cannot read those WFP records. Elevated read-only access
may be sufficient if collection is already enabled; its state is presently
unverified. Do not automatically enable global collection/auditing, change engine
ACLs or add capabilities/exemptions. Any additional diagnostic setup requires its
own exact scope and review.

Only after the strict network gate passes may the model-free ROCm/kernel/import
checks run. Broader filesystem/device/security needs must be reported before
changing them. Real checkpoint access/loading/generation and UI activation still
require the separate approvals listed in [the SDXL worker plan](OFFLINE_SDXL_WORKER.md).

## Rollback procedure — recorded, not executed

1. Stop/reap only jobs owned by this prototype. All test jobs were reaped; verify
   there are no remaining owned processes before changing profile resources.
2. Review the private profile and staging records, confirming the exact profile
   name/SID binding and root under `.local-data/offline-sandbox/<run-id>`.
3. Remove only that SID's explicit grants from the newly staged tree. Do not
   restore broad inherited access, change another profile or touch original paths.
4. Delete only the recorded per-user development profile using
   `DeleteAppContainerProfile`; verify its result. The private rollback helper
   requires an explicit `--apply`, checks the name/SID binding and leaves staged
   project files in place. It has not been executed.
5. Preserve staged files/evidence for review; no recursive deletion, Git reset,
   environment uninstall or original-file move is required. Continue using the
   unchanged `.venv` for the desktop application.
