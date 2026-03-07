# Self-Correction Coding Assistant Agent (Track 5+6)

### Machine Learning @ Berkeley · Spring 2026 · Google GKE

Google x ML@Berkeley Collaboration
Timeline: March 2, 2026 - May 4, 2026 (Spring Break: March 23-27, 2026)

## 👥 Contributors

- `Cici Cai` 🎓
- `Skyla Ma` 🎓
- `Robin Holzinger` 🎓

## 📘 Overview

Build a long-running coding agent on GKE that can iteratively fix failing Python code/tests, while prioritizing secure tool execution and policy guardrails.

## 🎯 Key Deliverables

- Stable single-agent runtime on GKE
- LangGraph-first implementation path (framework selection finalized in Week 2)
- Secure tool execution in isolated ephemeral sandboxes on GKE (Track 5)
- Network policy guardrails + auditability for tool use (Track 6)
- Demo-ready workflow (10-15 minute reproducible demo)
- Final architecture diagram and concise findings report

## 🌐 Repository

🔗 [github.com/robinholzi/sp26-google-gke-coding-agent](https://github.com/robinholzi/sp26-google-gke-coding-agent)

## 🚀 Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/robinholzi/sp26-google-gke-coding-agent.git
   cd <repo-directory>
   ```

2. Install [pixi](https://pixi.sh) if you haven't already:

   ```bash
   brew install pixi
   ```

3. Install the pixi environment:

   ```bash
   pixi install
   pixi run postinstall

   # Register pre-commit hooks
   pixi run pre-commit-install

   # Run pre-commit hooks on all files once
   pixi run pre-commit run --all
   ```

   The default Pixi environment now includes infra tooling: `gcloud`, `terraform`, `sops`, and `age`.

4. Run the test suite:

   ```bash
   pixi run pytest
   ```

5. Optional: Use direnv to automatically activate the pixi environment:
   ```bash
   # one-time setup
   brew install direnv
   direnv allow
   ```

## ☁️ Terraform (GCP + SOPS)

Terraform is configured in `cloud/` for GCP + GKE. Secrets are managed in a SOPS file (`secrets/secrets.sops.yaml`).

`make tf-plan` / `make tf-apply` now auto-runs GCP auth and project setup (login + ADC + quota project + project config + required APIs) when needed.

```bash
cp cloud/config.auto.tfvars.example cloud/config.auto.tfvars
# set project_id and other non-sensitive values in cloud/config.auto.tfvars

make tf-secrets-template
# fill sensitive values in secrets/secrets.sops.yaml
make gcp-kms-bootstrap
make tf-secrets-encrypt-kms
make tf-plan
make tf-apply  # This creates a GKE cluster (can take ~10 min)

# SOPS / Secrets workflow:
make tf-secrets-decrypt
make tf-secrets-edit
make tf-secrets-encrypt-kms
```

Headless login (no browser auto-open):

```bash
make GCLOUD_LOGIN_FLAGS=--no-launch-browser tf-plan
```

## 🤖 Dummy GKE Workflow Starter

This repo includes a minimal Python workflow starter that runs on GKE:

- Python entrypoint: `sp26_gke.workflows.gke_dummy_job`
- Pixi task: `pixi run gke-dummy-job`
- Dockerfile: `cloud/docker/gke-dummy.Dockerfile`
- Kubernetes manifests: `cloud/k8s/dummy-workflow/`

Deploy flow:

```bash
make gke-dummy-build
make gke-dummy-push
make gke-dummy-run-once      # one-off Job
# or:
make gke-dummy-schedule      # CronJob (every 30 min)
```

`make gke-dummy-push` now auto-runs gcloud auth checks, configures Docker for Artifact Registry, and creates the `gke-workflows` repository if missing.

Read logs:

```bash
make gke-dummy-logs
```

## 🧪 Track 5+6 Focus

Track 5: Secure Tool Execution & Isolation (Agent Sandbox)

- Run untrusted AI-generated tool code in ephemeral, isolated environments
- Enforce secure runtime defaults (`gVisor` + default-deny network policy)
- Evaluate reliability and developer-velocity impact

Track 6: (Network)Policy Guardrails & Auditability

- Add enforceable allow/deny controls for commands, images, and outbound destinations
- Capture end-to-end audit logs for tool execution decisions
- Measure safety controls versus task completion and latency

## 🗓️ Timeline (Proposal)

1. Week of March 2, 2026: scope, metrics, and GKE access setup
2. Week of March 9, 2026: framework selection + local validation
3. Week of March 16, 2026: first stable GKE deployment + logging
4. Week of March 30, 2026: core loop + retries + latency baseline
5. Week of April 6, 2026: quality checks + framework comparison
6. Week of April 13, 2026: observability dashboard + throughput smoke test + security checklist
7. Week of April 20, 2026: runtime hardening + failure drills
8. Week of April 27, 2026: rehearsals + report delivery
9. Week of May 4, 2026: demo day 🎉

## 📁 Directory Structure

- `cloud/`: GKE and infrastructure assets
- `dev/`: local development helpers
- `docs/`: project documentation
- `secrets/`: SOPS-managed sensitive values only
- `sp26_gke`: main agent codebase
- `tests/`: test suite

## 📝 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

Google GKE and ML@Berkeley collaboration team.
