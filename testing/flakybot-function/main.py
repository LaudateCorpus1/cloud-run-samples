# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import os
import subprocess
from datetime import datetime, timedelta


def write_xml_file(build_event):
    from junit_xml import TestSuite, TestCase

    build_id = build_event["id"]
    steps = build_event["steps"]
    outputs = build_event["results"]["buildStepOutputs"]
    test_cases = []

    for x in range(len(steps)):
        step = steps[x]
        status = step["status"]
        start_time, elapsed = get_elapsed_time(step)

        if status in ("FAILURE", "INTERNAL_ERROR", "TIMEOUT", "EXPIRED"):
            failure = outputs[x] or status
            test = TestCase(
                    name=step.get("id") or step.get("name"),
                    stderr=failure,
                    timestamp=start_time,
                    elapsed_sec=elapsed
                    )
            test.add_failure_info(build_event.get("logUrl"))

        else:
            test = TestCase(
                    name=step.get("id") or step.get("name"),
                    stdout=outputs[x] or status,
                    timestamp=start_time,
                    elapsed_sec=elapsed,
                    )
        test_cases.append(test)

    ts = TestSuite("Cloud Build Suite", test_cases)

    # create a new XML file with the results
    sponge_log = open("/tmp/sponge_log.xml", "w")
    sponge_log.write(TestSuite.to_xml_string([ts]))


def get_elapsed_time(step):
    timing = step.get("timing")
    if not timing:
        return None, None

    start_time = timing["startTime"].split(".")[0]
    end_time = timing["endTime"].split(".")[0]

    dt_start_time = datetime.fromisoformat(start_time)
    dt_end_time = datetime.fromisoformat(end_time)
    elapsed = (dt_end_time - dt_start_time).total_seconds()
    return start_time, elapsed


def send_to_flakybot(event, context):
    # Allow function framework to do all needed handling.
    data = base64.b64decode(event['data'])
    build_event = json.loads(data.decode("utf-8").strip())

    try:
        status = build_event.get("status")
        # flakybot should only run on complete builds
        if (status in("SUCCESS", "FAILURE", "INTERNAL_ERROR", "TIMEOUT", "EXPIRED")
            # flakybot should not run on Pull Requests
            and "_PR_NUMBER" not in build_event["substitutions"]):

            commit_sha = build_event["substitutions"]["COMMIT_SHA"]
            build_url = build_event.get("logUrl")
            build_id = build_event.get("id")
            entry = dict(
                severity="NOTICE",
                message=f"Processing logs from build {build_id} ({status})...",
                build_url=f"{build_url}",
                build_status=f"{status}",
                build_id=f"{build_id}",
                commit_sha=f"{commit_sha}",
            )
            print(json.dumps(entry))

            write_xml_file(build_event)
            out = subprocess.run(
                ["./flakybot", "-repo=GoogleCloudPlatform/cloud-run-samples",
                f"-commit_hash={commit_sha}", "-logs_dir=/tmp",
                f"-build_url={build_url}"],
                check=True, timeout=360,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout

            entry = dict(
                severity="INFO",
                message=out.decode('UTF-8'),
                build_url=f"{build_url}",
                build_status=f"{status}",
                build_id=f"{build_id}",
                commit_sha=f"{commit_sha}",
            )
            print(json.dumps(entry))
    except Exception as e:
        entry = dict(
            severity="ERROR",
            message=f"{e}",
            build_url=f"{build_url}",
            build_status=f"{status}",
            build_id=f"{build_id}",
            commit_sha=f"{commit_sha}",
        )
        print(json.dumps(entry))
        return (e, 500)
