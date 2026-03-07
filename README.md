# Market/Social Media Trend Analyst Agent

### Machine Learning @ Berkeley · Spring 2026 · Google GKE

Google x ML@Berkeley Collaboration
Timeline: March 2, 2026 - May 4, 2026 (Spring Break: March 23-27, 2026)

## 👥 Contributors

- `Alon Ragoler` 🎓
- `Annie Lauren Yun` 🎓
- `Robin Holzinger` 🎓

## 📘 Overview

Build a long-running agent on GKE that monitors social/news feeds and produces periodic sentiment and trend reports.

## 🎯 Key Deliverables

- Stable single-agent runtime on GKE
- Demo-ready workflow (10-15 minute reproducible demo)
- Final architecture diagram and concise findings report

## 🌐 Repository

🔗 [github.com/robinholzi/sp26-google-gke-social-media](https://github.com/robinholzi/sp26-google-gke-social-media)

## 🚀 Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/robinholzi/sp26-google-gke-social-media.git
   cd sp26-google-gke-social-media
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
