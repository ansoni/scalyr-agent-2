# Copyright 2014-2023 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import pathlib as pl
import subprocess
import http.server
import socketserver
import threading
import time

import pytest

from agent_build_refactored.utils.constants import (
    AGENT_VERSION,
    SOURCE_ROOT,
    CpuArch,
)
from agent_build_refactored.managed_packages.managed_packages_builders import (
    ALL_PACKAGE_BUILDERS,
    AGENT_AIO_PACKAGE_NAME,
    AGENT_NON_AIO_AIO_PACKAGE_NAME,
)
from tests.end_to_end_tests.managed_packages_tests.remote_machine_tests.tools import (
    create_packages_repo_root,
    get_packages_stable_version,
    is_builder_creates_aio_package,
)

from tests.end_to_end_tests.run_in_remote_machine import DISTROS


IN_REMOTE_MACHINE = bool(os.environ.get("IN_REMOTE_MACHINE"))


def add_cmd_args(parser, is_pytest_parser: bool):

    if is_pytest_parser:
        add_func = parser.addoption
    else:
        add_func = parser.add_argument

    add_func("--builder-name", dest="builder_name", required=True)

    add_func(
        "--package-type",
        dest="package_type",
        required=True,
        choices=["deb", "rpm"],
        help="Type of the package to test",
    )

    add_func(
        "--packages-source",
        dest="packages_source",
        required=False,
        help="Depending on the '--packages-source-type' option, directory or repo tarball with packages to test. "
             "If not specified, packages will be built inplace.",
    )

    add_func(
        "--packages-source-type",
        dest="packages_source_type",
        choices=["dir", "repo-tarball"],
        default="dir",
        required=False,
    )

    add_func(
        "--remote-machine-type",
        required=True,
        choices=["ec2", "docker"],
        help="Type of the remote machine for the test. For 'ec2' - run in AWS ec2 instance,"
             "'docker' - run in docker container, 'local', run locally.",
    )

    add_func(
        "--stable-packages-version",
        dest="stable_packages_version",
        required=False,
        help="Version of the latest stable version of package.",
    )

    add_func(
        "--distro-name",
        dest="distro_name",
        required=True,
        choices=DISTROS.keys(),
        help="Distribution to test.",
    )


def pytest_collection_modifyitems(config, items):
    if IN_REMOTE_MACHINE:
        return

    skip = pytest.mark.skip(reason="This test is only supposed to be run in a remote machine(docker or ec2)")
    for item in items:
        item.add_marker(skip)


def pytest_addoption(parser):
    if IN_REMOTE_MACHINE:
        add_cmd_args(parser, is_pytest_parser=True)


@pytest.fixture(scope="session")
def package_builder_name(request):
    """Name of the builder that build tested packages."""
    return request.config.option.builder_name


@pytest.fixture(scope="session")
def package_builder(package_builder_name):
    """Builder class that builds tested packges."""
    return ALL_PACKAGE_BUILDERS[package_builder_name]


@pytest.fixture(scope="session")
def package_type(request):
    return request.config.option.package_type


@pytest.fixture(scope="session")
def remote_machine_type(request):
    """
    Fixture with time of the remote machine where tests can run. For now that's ec2 or docker.
    """
    return request.config.option.remote_machine_type


@pytest.fixture(scope="session")
def distro_name(request):
    return request.config.option.distro_name


@pytest.fixture(scope="session")
def target_distro(distro_name):
    return DISTROS[distro_name]


@pytest.fixture(scope="session")
def use_aio_package(package_builder_name):
    """Fixture flag that tells that a tested package is AIO"""
    return is_builder_creates_aio_package(package_builder_name=package_builder_name)


@pytest.fixture(scope="session")
def agent_package_name(use_aio_package):
    if use_aio_package:
        return AGENT_AIO_PACKAGE_NAME
    else:
        return AGENT_NON_AIO_AIO_PACKAGE_NAME


@pytest.fixture(scope="session")
def stable_packages_version(request):
    return get_packages_stable_version(
        version=request.config.option.stable_packages_version
    )


@pytest.fixture(scope="session")
def packages_repo_root(request, tmp_path_factory, package_builder, stable_packages_version, package_type):
    """
    Root directory which is served by the mock web server.
    The mock repo is located in ./repo folder, the public key is located in ./repo_public_key.gpg
    :return:
    """

    return create_packages_repo_root(
        packages_source_type=request.config.option.packages_source_type,
        packages_source=request.config.option.packages_source,
        package_builder=package_builder,
        package_type=package_type,
        stable_packages_version=stable_packages_version,
        output_dir=tmp_path_factory.mktemp("packages_repo_root")
    )


@pytest.fixture(scope="session")
def repo_root(packages_repo_root):
    """Root directory of the mock repository."""
    return packages_repo_root / "repo"


@pytest.fixture(scope="session")
def server_url(packages_repo_root):
    """
    This fixture prepares http server with package repository and other needed files.
    """

    # Create web server which serves repo and public key file.
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(packages_repo_root), **kwargs)

    with socketserver.TCPServer(("", 0), Handler) as httpd:
        repo_server_thread = threading.Thread(target=httpd.serve_forever)
        repo_server_thread.start()

        time.sleep(1)

        yield f"http://localhost:{httpd.socket.getsockname()[1]}"

        httpd.shutdown()
        repo_server_thread.join()


@pytest.fixture(scope="session")
def repo_url(server_url):
    """Url to package repository"""

    return f"{server_url}/repo"


@pytest.fixture(scope="session")
def repo_public_key_url(server_url):
    return f"{server_url}/repo_public_key.gpg"


@pytest.fixture(scope="session")
def convenience_script_path(
    server_url, repo_url, repo_public_key_url, tmp_path_factory
):
    """
    Path to the convenience install script.
    We also start web server that serves mock repo with packages that have to be installed by the
    convenience script.
    """

    # Build convenience script with current repo and public key urls.
    render_install_script_path = (
        SOURCE_ROOT
        / "agent_build_refactored/managed_packages/convenience_install_script/render_install_agent_script.sh"
    )

    install_script_path = (
        tmp_path_factory.mktemp("install_script") / "install-scalyr-agent-2.sh"
    )

    subprocess.run(
        [
            "bash",
            str(render_install_script_path),
            repo_url,
            repo_url,
            repo_public_key_url,
            str(install_script_path),
        ],
        check=True,
    )

    yield install_script_path


def _get_package_path_from_repo(
    package_filename_glob: str, package_type: str, repo_root: pl.Path
):
    """Helper function that finds package inside repo root."""
    if package_type == "deb":
        packages_dir = repo_root / "pool/main/s"
    elif package_type == "rpm":
        packages_dir = repo_root
    else:
        raise Exception(f"Unknown package type: '{package_type}'")

    found = list(packages_dir.rglob(package_filename_glob))
    assert len(found) == 1
    return found[0]


def _arch_to_package_arch(package_type: str, arch: CpuArch = None):
    if package_type == "deb":
        mapping = {
            CpuArch.x86_64: "amd64",
            CpuArch.AARCH64: "arm64",
            None: "all",
        }
        return mapping[arch]

    if package_type == "rpm":
        mapping = {
            CpuArch.x86_64: "x86_64",
            CpuArch.AARCH64: "aarch64",
            None: "noarch",
        }
        return mapping[arch]


@pytest.fixture(scope="session")
def agent_package_path(
    repo_root,
    package_builder,
    agent_package_name,
    use_aio_package,
    package_type,
):
    if repo_root is None:
        return None

    if use_aio_package:
        package_arch = _arch_to_package_arch(
            package_type=package_type,
            arch=package_builder.ARCHITECTURE,
        )
    else:
        package_arch = _arch_to_package_arch(
            package_type=package_type,
            arch=None,
        )

    if package_type == "deb":
        package_filename_glob = f"{agent_package_name}_{AGENT_VERSION}_{package_arch}.{package_type}"
    elif package_type == "rpm":
        package_filename_glob = f"{agent_package_name}-{AGENT_VERSION}-1.{package_arch}.{package_type}"
    else:
        raise Exception(f"Unknown package type: {package_type}")

    return _get_package_path_from_repo(
        package_filename_glob=package_filename_glob,
        package_type=package_type,
        repo_root=repo_root,
    )
