"""Kubernetes job utilities: spawn, wait, read logs, cleanup, parse output."""

import time
import uuid

from kubernetes import client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

IMAGE = "us-central1-docker.pkg.dev/intrepid-stage-489905-m7/gke-workflows/coding-agent:latest"
NAMESPACE = "default"

_GVISOR_TOLERATION = {
    "key": "sandbox.gke.io/runtime",
    "operator": "Equal",
    "value": "gvisor",
    "effect": "NoSchedule",
}


def spawn_job(
    prefix: str,
    input_data: dict[str, str],
    command: list[str],
    needs_kubeconfig: bool = False,
    needs_google_api_key: bool = False,
    use_gvisor: bool = True,
) -> tuple[str, str]:
    """
    Create a ConfigMap with input_data and launch a GKE Job.

    Returns (job_name, cm_name).
    """
    uid = str(uuid.uuid4())[:8]
    job_name = f"{prefix}-{uid}"
    cm_name = f"{prefix}-input-{uid}"

    core_v1 = client.CoreV1Api()
    batch_v1 = client.BatchV1Api()

    core_v1.create_namespaced_config_map(
        namespace=NAMESPACE,
        body=client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=cm_name, namespace=NAMESPACE),
            data=input_data,
        ),
    )

    env: list[dict] = []
    if needs_google_api_key:
        env.append(
            {
                "name": "GOOGLE_API_KEY",
                "valueFrom": {
                    "secretKeyRef": {"name": "google-api-key", "key": "GOOGLE_API_KEY"}
                },
            }
        )
    if needs_kubeconfig:
        env.append({"name": "KUBECONFIG", "value": "/kubeconfig/config"})

    volume_mounts = [
        {"name": "input", "mountPath": "/input", "readOnly": True},
        {"name": "workspace", "mountPath": "/workspace"},
    ]
    volumes = [
        {"name": "input", "configMap": {"name": cm_name}},
        {"name": "workspace", "emptyDir": {}},
    ]
    if needs_kubeconfig:
        volume_mounts.append(
            {"name": "kubeconfig", "mountPath": "/kubeconfig", "readOnly": True}
        )
        volumes.append({"name": "kubeconfig", "configMap": {"name": "kubeconfig-cm"}})

    pod_spec: dict = {
        "restartPolicy": "Never",
        "containers": [
            {
                "name": "agent",
                "image": IMAGE,
                "command": command,
                "env": env,
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]},
                },
                "resources": {"limits": {"cpu": "500m", "memory": "512Mi"}},
                "volumeMounts": volume_mounts,
            }
        ],
        "volumes": volumes,
    }
    if use_gvisor:
        pod_spec["runtimeClassName"] = "gvisor"
        pod_spec["tolerations"] = [_GVISOR_TOLERATION]

    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name},
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 300,
            "template": {"spec": pod_spec},
        },
    }
    batch_v1.create_namespaced_job(namespace=NAMESPACE, body=job)
    print(f"[K8s] Spawned job {job_name}")
    return job_name, cm_name


def wait_for_logs(job_name: str) -> str:
    """Block until job completes, then return pod logs."""
    core_v1 = client.CoreV1Api()
    batch_v1 = client.BatchV1Api()

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
        raise TimeoutError(f"Pod for {job_name} never appeared after 60s")

    elapsed = 0
    while True:
        status = batch_v1.read_namespaced_job_status(job_name, namespace=NAMESPACE)
        if (status.status.succeeded or 0) >= 1 or (status.status.failed or 0) > 0:
            break
        if elapsed % 10 == 0:
            print(f"[K8s] Waiting for {job_name}... ({elapsed}s)")
        time.sleep(1)
        elapsed += 1

    outcome = "succeeded" if (status.status.succeeded or 0) >= 1 else "failed"
    print(f"[K8s] Job {job_name} {outcome} after {elapsed}s")

    try:
        return core_v1.read_namespaced_pod_log(name=pod_name, namespace=NAMESPACE)
    except ApiException as e:
        print(f"[K8s] Error reading logs from {pod_name}: {e}")
        return ""


def cleanup_job(job_name: str, cm_name: str) -> None:
    """Delete a job and its associated input ConfigMap."""
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
        core_v1.delete_namespaced_config_map(name=cm_name, namespace=NAMESPACE)
    except ApiException:
        pass


def parse_section(logs: str, start_marker: str, end_marker: str) -> str:
    """Extract text between arbitrary start and end markers in logs."""
    lines = logs.splitlines()
    capturing = False
    result = []
    for line in lines:
        if start_marker in line:
            capturing = True
        elif end_marker in line:
            break
        elif capturing:
            result.append(line)
    return "\n".join(result).strip()


def parse_output(logs: str) -> str:
    """Extract text between AGENT OUTPUT START and AGENT OUTPUT END markers."""
    return parse_section(logs, "--- AGENT OUTPUT START ---", "--- AGENT OUTPUT END ---")
