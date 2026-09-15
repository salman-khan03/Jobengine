# Engineering documentation

| Document | What it answers |
|---|---|
| [roleradar.md](roleradar.md) | **The decision layer**: grounding contract, constraint gate, scoring, and outcome-based ranking evaluation |
| [architecture.md](architecture.md) | How the system is put together and why it's split that way |
| [database.md](database.md) | Schema, ER diagram, indexes, and the non-obvious modelling choices |
| [api-contract.md](api-contract.md) | Every endpoint, error semantics, and conventions (+ [openapi.json](openapi.json)) |
| [threat-model.md](threat-model.md) | Assets, trust boundaries, STRIDE threats, and which are still open |
| [testing-strategy.md](testing-strategy.md) | What's tested, what isn't, and why |
| [decisions.md](decisions.md) | ADRs — each with the alternatives considered and the cost accepted |
| [known-limitations.md](known-limitations.md) | Everything wrong with this, written down first |
| [cost-estimate.md](cost-estimate.md) | What it costs to run, on three different setups |
| [measurements.md](measurements.md) | Every measured number, with methodology and caveats |
| [case-study-search-latency.md](case-study-search-latency.md) | The engineering failure story: three bugs found by measuring |
| [user-study.md](user-study.md) | Protocol for the 5–15 person study (not yet run) |
| [public-launch-kit.md](public-launch-kit.md) | Demo script, article outline, LinkedIn draft (unpublished) |
| [../infra/README.md](../infra/README.md) | AWS pipeline + CloudWatch as Terraform (never applied) |
| [../DEPLOY.md](../DEPLOY.md) | Deployment guide |
| [../loadtest/README.md](../loadtest/README.md) | Load-testing harness and how to record results |

## A note on numbers

No performance, adoption, or reliability figure appears anywhere in this
repository unless it came from an actual measurement, with the method stated.
Where a number would normally go and no measurement exists yet, the docs say so
explicitly rather than estimating. [measurements.md](measurements.md) records
what has been measured, how, and on what hardware;
[known-limitations.md](known-limitations.md) lists what is still unmeasured.
