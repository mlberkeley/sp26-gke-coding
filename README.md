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

## 📁 Directory Structure

- `cloud/`: GKE and infrastructure assets
- `dev/`: local development helpers
- `docs/`: project documentation
- `sp26_gke`: main agent codebase
- `tests/`: test suite

## 📝 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

Google GKE and ML@Berkeley collaboration team.
