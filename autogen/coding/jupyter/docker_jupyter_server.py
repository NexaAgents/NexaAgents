from __future__ import annotations

from pathlib import Path
import sys
from time import sleep
from types import TracebackType
import uuid
from typing import Dict, Optional, Union
import docker
import secrets
import io
import atexit
from .jupyter_client import JupyterClient

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


from .base import JupyterConnectable, JupyterConnectionInfo

__all__ = ["DockerIPythonCodeExecutor"]


KERNEL_DOCKERFILE = """FROM quay.io/jupyter/docker-stacks-foundation

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER ${NB_UID}
RUN mamba install --yes jupyter_kernel_gateway ipykernel && \
    mamba clean --all -f -y && \
    fix-permissions "${CONDA_DIR}" && \
    fix-permissions "/home/${NB_USER}"

ENV TOKEN="UNSET"
CMD python -m jupyter kernelgateway --KernelGatewayApp.ip=0.0.0.0 \
    --KernelGatewayApp.port=8888 \
    --KernelGatewayApp.auth_token="${TOKEN}" \
    --JupyterApp.answer_yes=true \
    --JupyterWebsocketPersonality.list_kernels=true

EXPOSE 8888

WORKDIR "${HOME}"
"""

def _wait_for_ready(container: docker.Container, timeout: int = 60, stop_time: int = 0.1) -> None:
    elapsed_time = 0
    while container.status != "running" and elapsed_time < timeout:
        sleep(stop_time)
        elapsed_time += stop_time
        container.reload()
        continue
    if container.status != "running":
        raise ValueError("Container failed to start")


class DockerJupyterServer(JupyterConnectable):
    class GenerateToken:
        pass

    def __init__(
        self,
        *,
        image_name: str = "autogen-jupyterkernelgateway",
        container_name: Optional[str] = None,
        auto_remove: bool = True,
        stop_container: bool = True,
        docker_env: Dict[str, str] = {},
        token: Union[str, GenerateToken] = GenerateToken(),
    ):
        """Start a Jupyter kernel gateway server in a Docker container.

        Args:
            image_name (str, optional): Image to use. If this image does not exist,
                then the bundled image will be built and tagged with this name.
            container_name (Optional[str], optional): Name of the container to start.
                A name will be generated if None.
            auto_remove (bool, optional): If true the Docker container will be deleted
                when it is stopped.
            stop_container (bool, optional): If true the container will be stopped,
                either by program exit or using the context manager
            docker_env (Dict[str, str], optional): Extra environment variables to pass
                to the running Docker container.
            token (Union[str, GenerateToken], optional): Token to use for authentication.
                If GenerateToken is used, a random token will be generated. Empty string
                will be unauthenticated.
        """
        if container_name is None:
            container_name = f"autogen-jupyterkernelgateway-{uuid.uuid4()}"

        # Check if the image exists
        client = docker.from_env()
        try:
            client.images.get(image_name)
        except docker.errors.ImageNotFound:
            # Build the image
            # Get this script directory
            here = Path(__file__).parent
            dockerfile = io.BytesIO(KERNEL_DOCKERFILE.encode("utf-8"))
            client.images.build(path=here, fileobj=dockerfile, tag=image_name)

        if isinstance(token, DockerJupyterServer.GenerateToken):
            self._token = secrets.token_hex(32)
        else:
            self._token = token

        # Run the container
        env = {"TOKEN": self._token}
        env.update(docker_env)
        container = client.containers.run(
            image_name,
            detach=True,
            auto_remove=auto_remove,
            environment=env,
            publish_all_ports=True,
            name=container_name,
        )
        _wait_for_ready(container)
        container_ports = container.ports
        self._port = int(container_ports["8888/tcp"][0]["HostPort"])
        self._container_id = container.id

        def cleanup():
            try:
                inner_container = client.containers.get(container.id)
                inner_container.stop()
            except docker.errors.NotFound:
                pass

            atexit.unregister(cleanup)

        if stop_container:
            atexit.register(cleanup)

        self._cleanup_func = cleanup
        self._stop_container = stop_container

    @property
    def connection_info(self) -> JupyterConnectionInfo:
        return JupyterConnectionInfo(host="127.0.0.1", use_https=False, port=self._port, token=self._token)

    def stop(self):
        self._cleanup_func()

    def get_client(self) -> JupyterClient:
        return JupyterClient(self.connection_info)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: Optional[type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        self.stop()
