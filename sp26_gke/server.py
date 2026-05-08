"""FastAPI endpoint that submits user code to the coding-agent GKE job."""

from fastapi import FastAPI

from ui.k8s_client import submit

app = FastAPI()


@app.post("/repair")
def repair(code: str) -> dict[str, str]:
    job_name, cm_name = submit(code)
    return {"job": job_name, "configmap": cm_name}
