"""Container orchestrator — manages agent container lifecycle.

Supports two backends, selected by SU_ORCHESTRATOR env var:
  - "docker" (default): uses Docker SDK, for local development
  - "kubernetes": uses K8s Jobs API, for cluster deployment

Agents POST status/done to the orchestrator's API endpoints, which
write to the database. The /done endpoint signals an in-process
asyncio.Event so the orchestrator wakes up instantly when all agents
finish — no polling.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import os
import uuid as _uuid

import httpx

logger = logging.getLogger(__name__)

AGENT_PORT = 8080
AGENT_STARTUP_TIMEOUT = 120
AGENT_RUN_TIMEOUT = 1800

_run_trackers: dict[str, dict] = {}
_run_cancel_flags: set[str] = set()
_active_run_cleanups: dict[str, tuple["AgentOrchestrator", list[str]]] = {}


class RunCancelledError(Exception):
    """Raised when a run is cancelled while agents are active."""


def is_run_cancelled(run_id: str | None) -> bool:
    return run_id is not None and run_id in _run_cancel_flags


def request_run_cancel(run_id: str) -> None:
    _run_cancel_flags.add(run_id)
    tracker = _run_trackers.get(run_id)
    if tracker:
        tracker["cancelled"] = True
        tracker["event"].set()


def clear_run_cancel(run_id: str) -> None:
    _run_cancel_flags.discard(run_id)


async def stop_active_run(run_id: str) -> bool:
    """Signal cancellation and tear down any active agent containers."""
    request_run_cancel(run_id)
    entry = _active_run_cleanups.pop(run_id, None)
    if not entry:
        return False
    orchestrator, hosts = entry
    await orchestrator._cleanup(hosts)
    return True


def notify_agent_done(run_id: str) -> None:
    """Called by the /done endpoint when an agent finishes."""
    tracker = _run_trackers.get(run_id)
    if not tracker:
        return
    tracker["received"] += 1
    logger.info(
        "Run %s: %d/%d agents done",
        run_id,
        tracker["received"],
        tracker["expected"],
    )
    if tracker["received"] >= tracker["expected"]:
        tracker["event"].set()


def create_orchestrator(config: dict | None = None) -> AgentOrchestrator:
    """Factory — pick backend from SU_ORCHESTRATOR env var."""
    backend = os.environ.get("SU_ORCHESTRATOR", "docker")
    if backend == "kubernetes":
        return KubernetesOrchestrator(config=config)
    return DockerOrchestrator(config=config)


class AgentOrchestrator(abc.ABC):
    """Base class for agent container orchestration."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.agent_image = os.environ.get("SU_AGENT_IMAGE", "synthetic-users:latest")

    async def run_all(
        self,
        personas: list[dict],
        phases: list[dict],
        model: str,
        repo_url: str,
        run_persona_map: dict[str, str],
        run_id: str | None = None,
    ) -> None:
        """Start one agent per persona, wait for all to finish."""
        agent_hosts = []
        try:
            if is_run_cancelled(run_id):
                raise RunCancelledError(f"Run {run_id} cancelled")

            agent_hosts = await self._start_agents(personas)
            if run_id:
                _active_run_cleanups[run_id] = (self, agent_hosts)

            if is_run_cancelled(run_id):
                raise RunCancelledError(f"Run {run_id} cancelled")

            await self._wait_for_healthy(agent_hosts)

            orchestrator_url = self._build_orchestrator_url(run_id)

            for persona, host in zip(personas, agent_hosts):
                if is_run_cancelled(run_id):
                    raise RunCancelledError(f"Run {run_id} cancelled")
                await self._dispatch_run(
                    host=host,
                    persona=persona,
                    phases=phases,
                    model=model,
                    repo_url=repo_url,
                    config=self.config,
                    orchestrator_url=orchestrator_url,
                )

            await self._wait_for_completion(
                run_id=run_id,
                persona_count=len(personas),
            )
        finally:
            if run_id:
                _active_run_cleanups.pop(run_id, None)
                clear_run_cancel(run_id)
            await self._cleanup(agent_hosts)

    def _build_orchestrator_url(self, run_id: str | None) -> str:
        host = os.environ.get("SU_ORCHESTRATOR_HOST", "localhost")
        port = os.environ.get("SU_ORCHESTRATOR_PORT", "8000")
        return f"http://{host}:{port}/api/runs/{run_id}"

    @abc.abstractmethod
    async def _start_agents(self, personas: list[dict]) -> list[str]:
        """Start agent containers/pods. Returns list of hostnames."""

    @abc.abstractmethod
    async def _cleanup(self, hosts: list[str]) -> None:
        """Remove agent containers/pods."""

    def _base_env(self) -> dict[str, str]:
        env: dict[str, str] = {"SU_ROLE": "agent"}
        for key in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_VERTEX_PROJECT_ID",
            "CLOUD_ML_REGION",
            "MODELS_CORP_API_KEY",
            "MODELS_CORP_URL",
            "NVIDIA_API_KEY",
            "NVIDIA_NIM_BASE_URL",
            "NVIDIA_NIM_MODEL",
            "NVIDIA_NIM_FALLBACK_MODEL",
            "NVIDIA_NIM_ENABLE_THINKING",
        ):
            val = os.environ.get(key, "")
            if val:
                env[key] = val
        gcp_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if gcp_creds:
            env["GOOGLE_APPLICATION_CREDENTIALS"] = "/gcp/credentials.json"
        return env

    def _gcp_volume_mounts(self) -> dict[str, dict] | None:
        host_path = os.environ.get("SU_GCP_CREDENTIALS_HOST_PATH")
        if host_path:
            return {host_path: {"bind": "/gcp/credentials.json", "mode": "ro"}}
        return None

    async def _wait_for_healthy(
        self, hosts: list[str], timeout: int = AGENT_STARTUP_TIMEOUT
    ) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for host in hosts:
                url = f"http://{host}:{AGENT_PORT}/health"
                for _ in range(timeout):
                    try:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            logger.info("Agent %s is healthy", host)
                            break
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(1)
                else:
                    raise RuntimeError(
                        f"Agent {host} did not become healthy within {timeout}s"
                    )

    async def _dispatch_run(
        self,
        host: str,
        persona: dict,
        phases: list[dict],
        model: str,
        repo_url: str,
        config: dict,
        orchestrator_url: str,
    ) -> None:
        """POST /run to agent (returns 202 immediately)."""
        url = f"http://{host}:{AGENT_PORT}/run"
        payload = {
            "persona": persona,
            "phases": phases,
            "repo_url": repo_url,
            "model": model,
            "config": config,
            "orchestrator_url": orchestrator_url,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        logger.info("Dispatched run to %s for %s", host, persona["name"])

    async def _wait_for_completion(
        self,
        run_id: str | None,
        persona_count: int,
        timeout: int = AGENT_RUN_TIMEOUT,
    ) -> None:
        """Wait for all agents to call /done via asyncio.Event."""
        if not run_id:
            return

        tracker = {
            "expected": persona_count,
            "received": 0,
            "event": asyncio.Event(),
        }
        _run_trackers[run_id] = tracker

        started = asyncio.get_event_loop().time()
        try:
            while True:
                if is_run_cancelled(run_id) or tracker.get("cancelled"):
                    raise RunCancelledError(f"Run {run_id} cancelled")
                elapsed = asyncio.get_event_loop().time() - started
                remaining = max(timeout - elapsed, 0)
                if remaining == 0:
                    raise RuntimeError(
                        f"Only {tracker['received']}/{persona_count} agents finished "
                        f"within {timeout}s for run {run_id}"
                    )
                try:
                    await asyncio.wait_for(tracker["event"].wait(), timeout=min(1.0, remaining))
                except asyncio.TimeoutError:
                    continue
                if is_run_cancelled(run_id) or tracker.get("cancelled"):
                    raise RunCancelledError(f"Run {run_id} cancelled")
                break
        finally:
            _run_trackers.pop(run_id, None)


# ── Docker backend ───────────────────────────────────────────────────


class DockerOrchestrator(AgentOrchestrator):
    """Local development: manages agent containers via Docker SDK."""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.network_name = os.environ.get(
            "SU_DOCKER_NETWORK", "synthetic-users_default"
        )
        self._docker_client = None
        self._containers: dict[str, object] = {}

    async def _start_agents(self, personas: list[dict]) -> list[str]:
        import docker

        self._docker_client = docker.from_env()
        env = self._base_env()
        volumes = self._gcp_volume_mounts() or {}
        hosts = []

        for persona in personas:
            name = f"su-agent-{persona['id'][:8]}"
            try:
                old = self._docker_client.containers.get(name)
                old.remove(force=True)
                logger.info("Removed stale container %s", name)
            except docker.errors.NotFound:
                pass

            image = persona.get("environment_image") or self.agent_image

            try:
                container = self._docker_client.containers.run(
                    image,
                    detach=True,
                    name=name,
                    environment=env,
                    network=self.network_name,
                    volumes=volumes,
                    remove=False,
                )
                self._containers[name] = container
                hosts.append(name)
                logger.info("Started Docker container %s for %s", name, persona["name"])
            except Exception as e:
                logger.exception("Failed to start container for %s", persona["name"])
                raise RuntimeError(
                    f"Failed to start agent container for {persona['name']}: {e}"
                ) from e

        return hosts

    async def _cleanup(self, hosts: list[str]) -> None:
        for name in hosts:
            container = self._containers.get(name)
            if container:
                try:
                    container.stop(timeout=10)
                    container.remove(force=True)
                    logger.info("Removed Docker container %s", name)
                except Exception:
                    logger.warning(
                        "Failed to clean up container %s", name, exc_info=True
                    )
        if self._docker_client:
            self._docker_client.close()
        self._containers.clear()


# ── Kubernetes backend ───────────────────────────────────────────────


class KubernetesOrchestrator(AgentOrchestrator):
    """Cluster deployment: manages agent pods via K8s Jobs API."""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.namespace = os.environ.get("SU_K8S_NAMESPACE", "default")
        self._job_names: list[str] = []
        self._service_names: list[str] = []

    async def _start_agents(self, personas: list[dict]) -> list[str]:
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()

        batch_v1 = k8s_client.BatchV1Api()
        core_v1 = k8s_client.CoreV1Api()
        hosts = []

        env_vars = [
            k8s_client.V1EnvVar(name="SU_ROLE", value="agent"),
            k8s_client.V1EnvVar(
                name="ANTHROPIC_API_KEY",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="ANTHROPIC_API_KEY",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="ANTHROPIC_VERTEX_PROJECT_ID",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="ANTHROPIC_VERTEX_PROJECT_ID",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="CLOUD_ML_REGION",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="CLOUD_ML_REGION",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="MODELS_CORP_API_KEY",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="MODELS_CORP_API_KEY",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="MODELS_CORP_URL",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="MODELS_CORP_URL",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="NVIDIA_API_KEY",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="NVIDIA_API_KEY",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="NVIDIA_NIM_BASE_URL",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="NVIDIA_NIM_BASE_URL",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="NVIDIA_NIM_MODEL",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="NVIDIA_NIM_MODEL",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="NVIDIA_NIM_FALLBACK_MODEL",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="NVIDIA_NIM_FALLBACK_MODEL",
                        optional=True,
                    )
                ),
            ),
            k8s_client.V1EnvVar(
                name="NVIDIA_NIM_ENABLE_THINKING",
                value_from=k8s_client.V1EnvVarSource(
                    secret_key_ref=k8s_client.V1SecretKeySelector(
                        name=os.environ.get("SU_K8S_SECRET", "simcrew"),
                        key="NVIDIA_NIM_ENABLE_THINKING",
                        optional=True,
                    )
                ),
            ),
        ]

        for persona in personas:
            suffix = _uuid.uuid4().hex[:8]
            job_name = f"su-agent-{suffix}"
            svc_name = job_name

            image = persona.get("environment_image") or self.agent_image

            container = k8s_client.V1Container(
                name="agent",
                image=image,
                ports=[k8s_client.V1ContainerPort(container_port=AGENT_PORT)],
                env=env_vars,
                resources=k8s_client.V1ResourceRequirements(
                    requests={"memory": "512Mi", "cpu": "250m"},
                    limits={"memory": "2Gi", "cpu": "2"},
                ),
            )

            job = k8s_client.V1Job(
                metadata=k8s_client.V1ObjectMeta(
                    name=job_name,
                    labels={"app": "su-agent", "su-run": suffix},
                ),
                spec=k8s_client.V1JobSpec(
                    backoff_limit=0,
                    ttl_seconds_after_finished=300,
                    template=k8s_client.V1PodTemplateSpec(
                        metadata=k8s_client.V1ObjectMeta(
                            labels={"app": "su-agent", "su-run": suffix},
                        ),
                        spec=k8s_client.V1PodSpec(
                            containers=[container],
                            restart_policy="Never",
                        ),
                    ),
                ),
            )

            service = k8s_client.V1Service(
                metadata=k8s_client.V1ObjectMeta(name=svc_name),
                spec=k8s_client.V1ServiceSpec(
                    selector={"app": "su-agent", "su-run": suffix},
                    ports=[
                        k8s_client.V1ServicePort(
                            port=AGENT_PORT, target_port=AGENT_PORT
                        )
                    ],
                ),
            )

            batch_v1.create_namespaced_job(namespace=self.namespace, body=job)
            core_v1.create_namespaced_service(namespace=self.namespace, body=service)
            self._job_names.append(job_name)
            self._service_names.append(svc_name)
            hosts.append(f"{svc_name}.{self.namespace}.svc.cluster.local")
            logger.info("Created K8s Job+Service %s for %s", job_name, persona["name"])

        return hosts

    async def _cleanup(self, hosts: list[str]) -> None:
        try:
            from kubernetes import client as k8s_client
            from kubernetes import config as k8s_config

            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()

            batch_v1 = k8s_client.BatchV1Api()
            core_v1 = k8s_client.CoreV1Api()

            for name in self._job_names:
                try:
                    batch_v1.delete_namespaced_job(
                        name=name,
                        namespace=self.namespace,
                        propagation_policy="Background",
                    )
                    logger.info("Deleted K8s Job %s", name)
                except Exception:
                    logger.warning("Failed to delete Job %s", name, exc_info=True)

            for name in self._service_names:
                try:
                    core_v1.delete_namespaced_service(
                        name=name, namespace=self.namespace
                    )
                    logger.info("Deleted K8s Service %s", name)
                except Exception:
                    logger.warning("Failed to delete Service %s", name, exc_info=True)
        except Exception:
            logger.warning("K8s cleanup failed", exc_info=True)

        self._job_names.clear()
        self._service_names.clear()
