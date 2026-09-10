# Policy Mix Cloud Development

## Local macOS environment

The local Conda environment is `agentsociety` (Python 3.12). `environment.yml`
pins AgentSociety 2.8.4 and Ray 2.55.1 to the cloud versions recorded below.
MCP is constrained to 1.x because this framework imports `mcp.server.fastmcp`,
which is no longer available in MCP 2.x.
The latest online documentation may describe a newer framework release.
To recreate the environment on another machine:

```sh
conda env create -f environment.yml
```

On this Mac, load the local configuration before running Python entry points:

```sh
cd /Users/zy/Desktop/AgentSoiety
conda activate agentsociety
set -a
source .env
set +a
```

The local `.env` is ignored by Git and has owner-only permissions (0600).
It configures `https://llmapi.fiblab.net/v1`; the initial model choices follow
the existing project configuration (`deepseek-v4-flash`, embedding `bge-m3`).
These model choices and credentials still require live API verification.
Create your own `.env` when recreating this environment; do not commit keys.

Offline validation (does not call a paid model):

```sh
python -m pip check
python tools/check_remote.py
python -B -m unittest discover -s tests -v
```

Despite its historical name, `check_remote.py` inspects the Python environment
where it is run. It replaces credentials with placeholders and blocks Python
network connections during its import checks. Local environment setup does
not grant a new experiment budget. Existing paid runners retain their budget,
authorization and loopback-proxy requirements; `.env` does not replace their
separate `.env.smoke` configuration or budget ledger.

## Code navigation

Start with [the architecture map](ARCHITECTURE.md) for shared execution and project lifecycle responsibilities, and [the domain glossary](CONTEXT.md) for the research terms.

## GitHub source distribution

This repository contains the canonical source, tests, selected research protocols,
and the six interface observation fixtures. It excludes local credentials, budget
ledgers, execution authorizations, raw run outputs, downloaded evidence, and temporary
files. Historical reports describe earlier local runs; links to excluded evidence
require the original local archive. A fresh clone is not a backup of cloud secrets
or budget state and does not authorize paid API execution.

The current implementation is documented in [research/v3_1/README.md](research/v3_1/README.md).
Offline tests use Python without starting a paid experiment:

```console
python -B -m unittest discover -s tests -v
```

当前代码在根目录原地维护，最新修订及验证入口见 [当前实现说明](research/v3_1/README.md)。版本号用于区分输入、状态与证据格式，不另建源码版本目录。

完整政策组合实验V3（组合、强度及顺序）的原始协议与历史执行证据见 [V3说明](research/v3_20260909/README.md)。旧版最小实验保留作基线与共用依赖；离线、框架验证与真实模型阶段分别记录，设计清单不构成阶段执行授权。

供水治理最小实验的协议、版本化代码、验证与接入结果入口见 [MVE说明](research/mve_20260909/README.md)。其中离线脚本矩阵、真实模型接入、定向接口用例与待批准的24次批次分别记录，不视为同类实验。

Connection target: `https://coder.fiblab.net`, workspace
`lanxinl29-gmail-com/policy-mix`, agent `main`.

- Local source: `D:\AgentSociety`
- Cloud development directory: `/home/coder/policy-mix`
- Preinstalled framework: `/app/packages/agentsociety2`
- Cloud Python: `/usr/local/bin/python`

The PowerShell entry point reuses the existing Coder Remote login. It never
copies or prints the saved session token. Do not commit credentials or `.env`
files. Keep changes out of the preinstalled framework unless explicitly needed.

## Commands

Run these from `D:\AgentSociety` in PowerShell:

```powershell
& .\tools\coder.ps1 list
& .\tools\coder.ps1 schedule show lanxinl29-gmail-com/policy-mix
& .\tools\open-cloud.ps1
& .\tools\coder.ps1 exec python /home/coder/policy-mix/tools/check_remote.py
```

The diagnostic uses temporary placeholder model settings and disables Python
network connections during imports. It does not start Ray or a simulation and
does not test actual model access. Its exit status covers file I/O and core
imports; inspect `pip_check` separately for preinstalled dependency conflicts.

`open-cloud.ps1` uses the verified remote URI and disables GPU acceleration for
that launch only. Close an existing VS Code instance first if you need the launch
option to take effect. This does not edit global preferences.

Use `coder.ps1 exec <command> [arguments]` for remote commands. The helper inserts
Coder's argument separator itself, because PowerShell consumes a script-level
`--`. Piped text is forwarded to the remote command's standard input.

## Verified on 2026-09-09

- Coder CLI 2.37.1: authenticated remote commands succeed. The existing Coder
  Remote extension updated its cached CLI and verified the vendor signature.
- VS Code 1.136.2: remote server, extension host, SSH tunnel, and the cloud
  `policy-mix` folder are connected. Earlier attempts hit a TLS connection reset;
  a fresh launch succeeded. GPU settings are not proven to be the cause.
- Container limits: 4 CPU cores and 32 GiB RAM, confirmed through cgroup values.
- Python 3.12.13; AgentSociety distribution metadata 2.8.4; Ray 2.55.1.
  AgentSociety's module-level `__version__` still says 2.8.3.
- File upload hashes match local files. Temporary cloud file read/write and
  offline core imports pass with process-local placeholder configuration.
- `pip check` reports two pre-existing conflicts: `transformers 5.15.0` requires
  `huggingface-hub >=1.5.0,<2.0` but 0.36.1 is installed; `pipx 1.16.6` requires
  `platformdirs >=4.6` but 4.5.1 is installed. No package versions were changed.
- The noninteractive SSH session does not provide `AGENTSOCIETY_LLM_API_KEY`,
  `AGENTSOCIETY_LLM_API_BASE`, or `AGENTSOCIETY_LLM_MODEL`. The smoke test reads
  its authorized key from the cloud-only `.env.smoke` file (mode 0600).
- Observed stop deadline: 2026-09-10 10:48:25 Asia/Shanghai. Check it again before
  long tasks; no schedule settings were changed.

## Working Rules

- Compare local and cloud file hashes before replacing existing code. There is
  no automatic bidirectional sync or overwrite policy.
- Use the cloud Python for execution. No local WSL or Conda deployment is needed
  for this connection workflow.
- Placeholder settings are not usable for experiments. The real smoke test below
  verifies basic execution, not research validity or all framework features.
- Check the current stop deadline before long runs. Background execution alone
  does not prevent Coder from stopping the workspace.
- Verify persistent-storage behavior before treating cloud-only results as a
  durable backup. Do not restart the workspace just to test this during work.

## Real AgentSociety Smoke Test

`tools/smoke_driver.py` imports the installed package directly:

```python
from agentsociety2.society import AgentSociety
from agentsociety2.env.env_router_actor import get_env_router_actor_class
```

It uses the official `PersonAgent`, `SimpleSocialSpace`, `AgentSociety.init()`,
`run(num_steps=1, tick=60)`, `ask()`, checkpoint, and replay implementations.
The environment runs in the package's Ray actor. No simulation engine was
reimplemented and no files under `/app/packages/agentsociety2` were modified.
The `AuditedSociety` subclass checks returned per-agent task results, because a
successful society time step alone does not prove every agent task succeeded.

Reference: [AgentSociety quickstart](https://agentsociety2.readthedocs.io/zh-cn/latest/quickstart.html).

### Results on 2026-09-09

- Real API probe returned `CLOUD_SMOKE_OK` using the platform's
  `https://llmapi.fiblab.net/v1` endpoint and `deepseek-v4-flash` model.
- Two official `PersonAgent` instances completed one step and returned nonempty
  readiness messages. The society advanced from 09:00 to 09:01.
- `SOCIETY.json`, `SOCIETY_STEP.json`, both agent checkpoints, the environment
  checkpoint, trace files, and replay JSONL records were saved.
- A separate query-only run restored the environment checkpoint without
  advancing the simulation. Both Ray sessions shut down afterward.
- The full combined test is **not a pass**: the original participant-name query
  exceeded the environment's exposed interface. `SimpleSocialSpace` exposes
  messaging/group tools, not a participant-profile listing tool. One attempt
  returned an empty-mailbox result; a later generated query was rejected for
  `import sys` by the package's safety checks. Those checks remain enabled.
- The source now asks for the simulation time through the helper's supported
  `get_current_time` tool. This correction has **not been re-tested with the
  real API**, because the authorized request allowance was exhausted.
- Initial code generation was truncated by a 1024-token output limit. A later
  attempt to disable reasoning returned HTTP 400 from the platform gateway.
  The final proxy uses the accepted request format and a 4096-token output cap.
- Total: 16 upstream requests, 15 HTTP 200 responses and one HTTP 400 response;
  22,088 reported input tokens and 25,549 reported output tokens. Displayed-price
  estimate: RMB 0.0878232 for reported usage. Conservative accounting including
  the unknown-usage HTTP 400 reservation: RMB 0.0943152. This is not a reconciled
  account bill.

The source run is `runs/smoke-20260909T040226.147544Z`; the supplemental query run
is `runs/smoke-20260909T041151.571299Z`. Earlier failures are retained separately.
`runs/verification-20260909.json` distinguishes core success from query failure.

### Test Commands

```powershell
& .\tools\coder.ps1 exec python -m unittest discover -s /home/coder/policy-mix/tests -v
& .\tools\coder.ps1 exec python /home/coder/policy-mix/tools/run_smoke.py
& .\tools\coder.ps1 exec python /home/coder/policy-mix/tools/run_smoke.py --resume-query /home/coder/policy-mix/runs/smoke-20260909T040226.147544Z/simulation
```

Do not run the paid commands again without a new allowance. The persistent
`runs/api-smoke-budget-20260909.json` ledger has reached its 16-request cap and
will block further upstream requests. It also enforces a conservative estimated
RMB 0.50 total cap, a single model, and single-choice non-streaming responses.
Do not delete the ledger to bypass the cap or start concurrent test controllers.
The cap is a test safeguard based on displayed prices, not a provider billing cap.

`tools/run_smoke.py` owns the real key and forwards requests through a loopback
proxy. Ray workers receive only a dummy loopback key. `.env.smoke` is excluded
from source control and result downloads. `tools/verify_smoke.py` validates the
saved evidence without imports of AgentSociety, network access, or API charges.
