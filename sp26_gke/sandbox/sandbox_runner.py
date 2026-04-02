# sp26_gke/sandbox/sandbox_runner.py
import base64
import time
import uuid

from kubernetes import client, config  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

config.load_kube_config(config_file="/kubeconfig/config")

batch_v1 = client.BatchV1Api()
core_v1 = client.CoreV1Api()

IMAGE = "us-central1-docker.pkg.dev/intrepid-stage-489905-m7/gke-workflows/coding-agent:latest"
NAMESPACE = "default"


def run_in_sandbox():
    with open("/workspace/buggy_script.py") as f:
        code = f.read()

    job_name = f"sandbox-{str(uuid.uuid4())[:8]}"

    print(f"[K8s] Creating sandbox Job: {job_name}")
    print(f"[K8s]   namespace:     {NAMESPACE}")
    print(f"[K8s]   image:         {IMAGE}")
    print("[K8s]   runtime:       gvisor  (gVisor/runsc — kernel-level isolation)")
    print("[K8s]   node pool:     sandbox.gke.io/runtime=gvisor")
    print("[K8s]   uid:           1000 (non-root)")
    print("[K8s]   root fs:       read-only")
    print("[K8s]   capabilities:  ALL dropped")
    print("[K8s]   priv escalation: disabled")
    print("[K8s]   cpu limit:     1 core")
    print("[K8s]   memory limit:  512Mi")

    job_manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name},
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 300,
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
                                "sh",
                                "-c",
                                (
                                    f"echo {base64.b64encode(code.encode()).decode()} | base64 -d > /workspace/buggy_script.py && "
                                    "cp /app/sp26_gke/tests/test_buggy_script.py /workspace/ && "
                                    "cd /workspace && "
                                    "python -u test_buggy_script.py"
                                ),
                            ],
                            "env": [
                                {
                                    "name": "GOOGLE_API_KEY",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "google-api-key",
                                            "key": "GOOGLE_API_KEY",
                                        }
                                    },
                                }
                            ],
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 1000,
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {"limits": {"cpu": "1", "memory": "512Mi"}},
                            "volumeMounts": [
                                {"name": "workspace", "mountPath": "/workspace"},
                                {
                                    "name": "kubeconfig",
                                    "mountPath": "/kubeconfig",
                                    "readOnly": True,
                                },
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "workspace", "emptyDir": {}},
                        {"name": "kubeconfig", "configMap": {"name": "kubeconfig-cm"}},
                    ],
                }
            },
        },
    }

    try:
        batch_v1.create_namespaced_job(namespace=NAMESPACE, body=job_manifest)
        print(f"[K8s] Job {job_name} created — waiting for pod to schedule...")
    except ApiException as e:
        print(f"[K8s] ERROR creating Job {job_name}: {e}")
        return ""

    # Wait for pod to appear and log scheduling info
    pod_name = None
    for _ in range(60):
        pods = core_v1.list_namespaced_pod(
            namespace=NAMESPACE, label_selector=f"job-name={job_name}"
        )
        if pods.items:
            pod = pods.items[0]
            pod_name = pod.metadata.name
            node = pod.spec.node_name or "pending"
            phase = pod.status.phase or "Pending"
            runtime = pod.spec.runtime_class_name or "default"
            print(f"[K8s] Pod:          {pod_name}")
            print(f"[K8s]   node:        {node}")
            print(f"[K8s]   phase:       {phase}")
            print(f"[K8s]   runtimeClass:{runtime}")
            break
        time.sleep(1)

    # Wait for job completion
    elapsed = 0
    while True:
        job_status = batch_v1.read_namespaced_job_status(job_name, namespace=NAMESPACE)
        succeeded = job_status.status.succeeded or 0
        failed = job_status.status.failed or 0
        active = job_status.status.active or 0
        if succeeded >= 1 or failed > 0:
            break
        if elapsed % 5 == 0:
            print(f"[K8s] Job {job_name} — active={active}, elapsed={elapsed}s")
        time.sleep(1)
        elapsed += 1

    outcome = "succeeded" if (job_status.status.succeeded or 0) >= 1 else "failed"
    print(f"[K8s] Job {job_name} {outcome} after {elapsed}s")

    # Fetch logs
    logs = ""
    if pod_name:
        try:
            logs = core_v1.read_namespaced_pod_log(name=pod_name, namespace=NAMESPACE)
            print(f"[K8s] Fetched {len(logs)} bytes of logs from {pod_name}")
        except ApiException as e:
            print(f"[K8s] ERROR fetching logs: {e}")
    else:
        pod_list = core_v1.list_namespaced_pod(
            namespace=NAMESPACE, label_selector=f"job-name={job_name}"
        )
        for pod in pod_list.items:
            logs += core_v1.read_namespaced_pod_log(
                name=pod.metadata.name, namespace=NAMESPACE
            )

    # Cleanup
    print(f"[K8s] Deleting Job {job_name}...")
    batch_v1.delete_namespaced_job(
        name=job_name,
        namespace=NAMESPACE,
        body=client.V1DeleteOptions(propagation_policy="Foreground"),
    )

    return logs
