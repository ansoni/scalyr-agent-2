#!/usr/bin/env bash
#----------------------------------------------------------------------------------------
# Runs agent smoketest for docker:
#    - Assumes that the current scalyr-agent-2 root directory contains the test branch and that
#       the VERSION file can be overwritten (ie. the scalyr-agent-2 directory is a "throwaway" copy.
#    - Launch agent docker image
#    - Launch uploader docker image (writes lines to stdout)
#    - Launch verifier docker image (polls for liveness of agent and
#       uploader, as well as verifies expected uploaded lines)
#
# Expects the following env vars:
#   SCALYR_API_KEY
#   SCALYR_SERVER
#   READ_API_KEY (Read api key. 'SCALYR_' prefix intentionally omitted to suppress in status -v)
#   CIRCLE_BUILD_NUM
#
# Expects following positional args:
#   $1 : smoketest image tag
#   $2 : 'syslog' or 'json' agent docker mode to test
#   $3 : max secs until test hard fails
#
# e.g. usage
#   smoketest_docker.sh scalyr/scalyr-agent-ci-smoketest:2 json 300
#----------------------------------------------------------------------------------------

# The following variables are needed
# Docker image in which runs smoketest python3 code
smoketest_image=$1

# Chooses json, api or syslog docker test.  Incorporated into container name which is then used by
# Verifier to choose the appropriate code to execute).
# log_mode="json"
log_mode=$2

# Max seconds before the test hard fails
max_wait=$3

# Name of a tested image
tested_image_name=$4

# We don't have an easy way to update base test docker images which come bundled
# with the smoketest.py file
# (.circleci/docker_unified_smoke_unit/smoketest/smoketest.py ->
# /tmp/smoketest.py) so we simply download this file from the github before running the tests.
# That's not great, but it works.
SMOKE_TESTS_SCRIPT_BRANCH=${CIRCLE_BRANCH:-"master"}
SMOKE_TESTS_SCRIPT_REPO=${CIRCLE_PROJECT_REPONAME:-"scalyr-agent-2"}

SMOKE_TESTS_SCRIPT_URL="https://raw.githubusercontent.com/scalyr/${SMOKE_TESTS_SCRIPT_REPO}/${SMOKE_TESTS_SCRIPT_BRANCH}/.circleci/docker_unified_smoke_unit/smoketest/smoketest.py"
DOWNLOAD_SMOKE_TESTS_SCRIPT_COMMAND="sudo curl -o /tmp/smoketest.py ${SMOKE_TESTS_SCRIPT_URL}"

#----------------------------------------------------------------------------------------
# Everything below this script should be fully controlled by above variables
#----------------------------------------------------------------------------------------

# Smoketest code (built into smoketest image)
smoketest_script="source ~/.bashrc && pyenv shell 3.7.3 && python3 /tmp/smoketest.py"

# Erase variables (to avoid subtle config bugs in development)
syslog_driver_option=""
syslog_driver_portmap=""
jsonlog_containers_mount=""
if [[ $log_mode == "docker-syslog" ]]; then
    syslog_driver_option="--log-driver=syslog --log-opt syslog-address=tcp://127.0.0.1:601"
    syslog_driver_portmap="-p 601:601"
elif [[ $log_mode == "docker-json" ]]; then
    jsonlog_containers_mount="-v /var/lib/docker/containers:/var/lib/docker/containers"
elif [[ $log_mode == "docker-api" ]]; then
    # Using Docker API mode aka docker_raw_logs: false
    echo ""
else
    echo "Unsupported log mode: ${log_mode}"
    exit 1
fi

# container names for all test containers
# The suffixes MUST be one of (agent, uploader, verifier) to match verify_upload::DOCKER_CONTNAME_SUFFIXES
contname_agent="ci-agent-${log_mode}-${CIRCLE_BUILD_NUM}-agent"
contname_uploader="ci-agent-${log_mode}-${CIRCLE_BUILD_NUM}-uploader"
contname_verifier="ci-agent-${log_mode}-${CIRCLE_BUILD_NUM}-verifier"


# Kill leftover containers
function kill_and_delete_docker_test_containers() {
    echo ""
    echo "::group::Killing and deleting all test containers..."
    echo ""

    for cont in $contname_agent $contname_uploader $contname_verifier
    do
        if [[ -n `docker ps | grep $cont` ]]; then
            docker kill $cont
        fi
        if [[ -n `docker ps -a | grep $cont` ]]; then
            docker rm $cont;
        fi
    done

    echo ""
    echo "Containers deleted..."
    echo "::endgroup::"
}

kill_and_delete_docker_test_containers
echo `pwd`

# Build agent docker image packager with fake version
echo "::group::Building docker image"
fakeversion=`cat VERSION`
fakeversion="${fakeversion}.ci"
echo $fakeversion > ./VERSION

docker image ls
echo "::endgroup::"


# Launch Agent container (which begins gathering stdout logs)
echo "::group::Launch Agent container (which begins gathering stdout logs)"
docker run -d --name ${contname_agent} \
-e SCALYR_API_KEY=${SCALYR_API_KEY} -e SCALYR_SERVER=${SCALYR_SERVER} \
-v /var/run/docker.sock:/var/scalyr/docker.sock \
${jsonlog_containers_mount} ${syslog_driver_portmap} \
"${tested_image_name}"
echo "::endgroup::"

# Capture agent short container ID
agent_hostname=$(docker ps --format "{{.ID}}" --filter "name=$contname_agent")
echo "Agent container ID == ${agent_hostname}"

# Launch Uploader container (only writes to stdout, but needs to query Scalyr to verify agent liveness)
# You MUST provide scalyr server, api key and importantly, the agent_hostname container ID for the agent-liveness
# query to work (uploader container waits for agent to be alive before uploading data)
echo "::group::Launch Uploader container"
docker run ${syslog_driver_option}  -d --name ${contname_uploader} ${smoketest_image} \
bash -c "${smoketest_script} ${contname_uploader} ${max_wait} \
--mode uploader \
--scalyr_server ${SCALYR_SERVER} \
--read_api_key ${READ_API_KEY} \
--agent_hostname ${agent_hostname}"
echo "::endgroup::"

# Capture uploader short container ID
uploader_hostname=$(docker ps --format "{{.ID}}" --filter "name=$contname_uploader")
echo "Uploader container ID == ${uploader_hostname}"
echo "Using smoketest.py script from ${SMOKE_TESTS_SCRIPT_BRANCH} branch and URL ${SMOKE_TESTS_SCRIPT_URL}"

function print_debugging_info_on_exit() {
    echo ""
    echo "::group::Docker logs for ${contname_agent} container"
    echo ""
    docker logs "${contname_agent}" || true
    echo "::endgroup::"

    # NOTE: We can't tail other two containers since they use syslog driver which
    # sends data to agent container.
    # TODO: Set agent debug level to 5

    echo ""
    echo "::group::Cating /var/log/scalyr-agent-2/agent_syslog.log log file"
    echo ""
    docker cp ${contname_agent}:/var/log/scalyr-agent-2/agent_syslog.log . || true
    cat agent_syslog.log || true
    echo "::endgroup::"

    echo ""
    echo "::group::Cating /var/log/scalyr-agent-2/docker_monitor.log log file"
    echo ""
    docker cp ${contname_agent}:/var/log/scalyr-agent-2/docker_monitor.log . || true
    cat docker_monitor.log || true
    echo "::endgroup::"

    kill_and_delete_docker_test_containers || true
}

# We want to run some commands on exit which may help with troubleshooting on
# test failures
trap print_debugging_info_on_exit EXIT

# Launch synchronous Verifier image (writes to stdout and also queries Scalyr)
# Like the Uploader, the Verifier also waits for agent to be alive before uploading data
echo ""
echo "::group::Begin synchronous verifier"
echo ""
docker run ${syslog_driver_option} -t --name ${contname_verifier} ${smoketest_image} \
bash -c "${DOWNLOAD_SMOKE_TESTS_SCRIPT_COMMAND} ; ${smoketest_script} ${contname_verifier} ${max_wait} \
--mode verifier \
--scalyr_server ${SCALYR_SERVER} \
--read_api_key ${READ_API_KEY} \
--agent_hostname ${agent_hostname} \
--uploader_hostname ${uploader_hostname} \
--debug true"
echo "::endgroup::"

echo ""
echo "Stopping agent."
echo ""
docker stop ${contname_agent}

echo ""
echo "Agent stopped, copying .coverage results."
echo ""
docker cp ${contname_agent}:/.coverage .
