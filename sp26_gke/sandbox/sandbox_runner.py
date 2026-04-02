# sp26_gke/sandbox/gke_runner.py
import base64
import time
import uuid

from kubernetes import client, config  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

config.load_kube_config(config_file="/kubeconfig/config")


batch_v1 = client.BatchV1Api()
core_v1 = client.CoreV1Api()


def run_in_sandbox():
    with open("/workspace/buggy_script.py") as f:
        code = f.read()

    job_name = "coding-agent"
    job_name = f"coding-agent-{str(uuid.uuid4())[:8]}"

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
                            "image": "us-central1-docker.pkg.dev/intrepid-stage-489905-m7/gke-workflows/coding-agent:latest",
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
    print("sandbox creating jobs")
    try:
        batch_v1.create_namespaced_job(namespace="default", body=job_manifest)
    except ApiException as e:
        print("Error creating Job:", e)
        return ""

    # Wait for completion
    while True:
        job_status = batch_v1.read_namespaced_job_status(job_name, namespace="default")
        if job_status.status.succeeded == 1 or (
            job_status.status.failed and job_status.status.failed > 0
        ):
            break
        time.sleep(1)

    # Fetch logs from pods
    pod_list = core_v1.list_namespaced_pod(
        namespace="default", label_selector=f"job-name={job_name}"
    )
    logs = ""
    for pod in pod_list.items:
        logs += core_v1.read_namespaced_pod_log(
            name=pod.metadata.name, namespace="default"
        )

    # Delete Job and associated pods
    batch_v1.delete_namespaced_job(
        name=job_name,
        namespace="default",
        body=client.V1DeleteOptions(propagation_policy="Foreground"),
    )
    print(logs)
    return logs
