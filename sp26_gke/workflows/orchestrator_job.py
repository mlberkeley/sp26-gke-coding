"""Entry point for the orchestrator GKE job."""

from sp26_gke.agent.orchestrator import run_orchestrator

if __name__ == "__main__":
    print("Starting multiagent orchestrator on GKE...")
    run_orchestrator()
