"""Kubernetes client for submitting and monitoring coding-agent jobs."""

import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from kubernetes import client, config  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

NAMESPACE = "default"
IMAGE = "us-central1-docker.pkg.dev/intrepid-stage-489905-m7/gke-workflows/coding-agent:latest"
KUBECONFIG = Path(__file__).parent.parent / "kubeconfig.yaml"


def _load_config() -> None:
    config.load_kube_config(config_file=str(KUBECONFIG))


def submit(code: str) -> tuple[str, str]:
    """
    Create a ConfigMap with the user's code and launch a coding-agent Job.

    Returns (job_name, configmap_name).
    """
    _load_config()
    uid = str(uuid.uuid4())[:8]
    job_name = f"coding-agent-{uid}"
    cm_name = f"user-code-{uid}"

    core_v1 = client.CoreV1Api()
    batch_v1 = client.BatchV1Api()

    configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=cm_name, namespace=NAMESPACE),
        data={"buggy_script.py": code},
    )
    core_v1.create_namespaced_config_map(namespace=NAMESPACE, body=configmap)

    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name},
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 600,
            "template": {
                "spec": {
                    "runtimeClassName": "gvisor",
                    "restartPolicy": "Never",
                    "tolerations": [
                        {
                            "key": "sandbox.gke.io/runtime",
                            "operator": "Equal",
                            "value": "gvisor",
                            "effect": "NoSchedule",
                        }
                    ],
                    "containers": [
                        {
                            "name": "agent",
                            "image": IMAGE,
                            "command": [
                                "python",
                                "/app/sp26_gke/workflows/orchestrator_job.py",
                            ],
                            "env": [
                                {"name": "KUBECONFIG", "value": "/kubeconfig/config"},
                                {
                                    "name": "GOOGLE_API_KEY",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "google-api-key",
                                            "key": "GOOGLE_API_KEY",
                                        }
                                    },
                                },
                            ],
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 1000,
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {"limits": {"cpu": "500m", "memory": "512Mi"}},
                            "volumeMounts": [
                                {
                                    "name": "kubeconfig",
                                    "mountPath": "/kubeconfig",
                                    "readOnly": True,
                                },
                                {
                                    "name": "user-code",
                                    "mountPath": "/input",
                                    "readOnly": True,
                                },
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "kubeconfig", "configMap": {"name": "kubeconfig-cm"}},
                        {"name": "user-code", "configMap": {"name": cm_name}},
                    ],
                }
            },
        },
    }

    batch_v1.create_namespaced_job(namespace=NAMESPACE, body=job)
    return job_name, cm_name


def stream_logs(job_name: str) -> Iterator[str]:
    """Yield log lines from the coding-agent job as they arrive."""
    _load_config()
    core_v1 = client.CoreV1Api()

    pod_name = None
    for _ in range(60):
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE, label_selector=f"job-name={job_name}"
        )
        if pods.items:
            pod_name = pods.items[0].metadata.name
            break
        time.sleep(1)

    if not pod_name:
        raise TimeoutError(f"Pod for job {job_name} never appeared after 60s")

    for _ in range(120):
        pod = core_v1.read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
        phase = pod.status.phase
        if phase in ("Running", "Succeeded", "Failed"):
            break
        time.sleep(1)

    response = core_v1.read_namespaced_pod_log(
        name=pod_name,
        namespace=NAMESPACE,
        follow=True,
        _preload_content=False,
    )
    for chunk in response:
        yield from chunk.decode("utf-8", errors="replace").splitlines()


def get_status(job_name: str) -> str:
    """Return 'pending', 'running', 'succeeded', or 'failed'."""
    _load_config()
    batch_v1 = client.BatchV1Api()
    try:
        job = batch_v1.read_namespaced_job_status(job_name, namespace=NAMESPACE)
        if job.status.succeeded:
            return "succeeded"
        if job.status.failed:
            return "failed"
        if job.status.active:
            return "running"
        return "pending"
    except ApiException:
        return "unknown"


def cleanup(job_name: str, configmap_name: str) -> None:
    """Delete the job and its associated ConfigMap."""
    _load_config()
    batch_v1 = client.BatchV1Api()
    core_v1 = client.CoreV1Api()

    try:
        batch_v1.delete_namespaced_job(
            name=job_name,
            namespace=NAMESPACE,
            body=client.V1DeleteOptions(propagation_policy="Foreground"),
        )
    except ApiException:
        pass

    try:
        core_v1.delete_namespaced_config_map(name=configmap_name, namespace=NAMESPACE)
    except ApiException:
        pass
