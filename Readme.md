# HyperExecute Automation Script

A Python script that automates running a JMeter or Gatling performance test on LambdaTest HyperExecute: it triggers the job, monitors it to completion, waits for artifacts to be ready, and downloads the results as a zip file.

Follow the steps below in order to go from a clean checkout to a downloaded test report.

## Step 1: Check prerequisites

- Python 3.7+
- A LambdaTest account with access to HyperExecute
- A HyperExecute project already set up with a `.jmx` test plan (JMeter) or a Gatling simulation file/project (either already in the project workspace, or on your local machine to upload in Step 4)

## Step 2: Install dependencies

```bash
pip install -r requirements.txt
```

This installs `requests`, the only dependency the script needs.

## Step 3: Get your LambdaTest credentials

You need three values:

| Value | Where to find it |
|-------|-------------------|
| **Username** | LambdaTest → Profile → Account Details |
| **API Key / Access Key** | LambdaTest → Profile → Access Key (regenerate if you don't have one) |
| **Project ID** | HyperExecute → Projects → select your project → copy the ID from the URL |

## Step 4: Configure your credentials

Choose one of the following. Environment variables are recommended so secrets never end up in shell history or CI logs.

**Option A — Environment variables (recommended)**
```bash
export LT_USERNAME=your_username
export LT_ACCESS_KEY=your_api_key
export HYPEREXECUTE_PROJECT_ID=your_project_id
```

**Option B — `.env` file**
```bash
# .env
LT_USERNAME=your_username
LT_ACCESS_KEY=your_api_key
HYPEREXECUTE_PROJECT_ID=your_project_id
```
```bash
source .env
```

**Option C — Command-line flags**
```bash
python hyperexecute_automation.py \
  --username your_username \
  --api-key your_api_key \
  --project-id your_project_id
```

## Step 5 (optional): Point the script at your JMX file

The script needs to know where the `.jmx` test plan lives.

- **Already uploaded to the project workspace?** Pass its path with `--jmx-path` (or set `HYPEREXECUTE_JMX_PATH`). Default: `Ecommerce.jmx`.
- **Only have it locally?** Upload it (and any supporting files, like CSV data) as part of the run with `--upload-jmx`:

```bash
# Upload a single file
python hyperexecute_automation.py --upload-jmx ./test.jmx

# Upload a whole folder (jmx + CSV data), preserving structure
python hyperexecute_automation.py --upload-jmx ./test-plan/
```

If the upload returns a remote path, the script uses it automatically and `--jmx-path` is ignored.

## Step 6: Run the script

With credentials set via environment variables (Step 4, Option A):

```bash
python hyperexecute_automation.py
```

Defaults: 100 users, 120s duration, 60s ramp-up, concurrency 1.

The script will:
1. **Trigger** the job with your JMeter configuration
2. **Monitor job status** until it completes (waits silently during VM provisioning)
3. **Monitor artifact status** until the results are ready
4. **Download** the results as a zip file

## Step 7: Customize the test parameters

```bash
python hyperexecute_automation.py \
  --users 200 \
  --duration 300 \
  --rampup 120 \
  --concurrency 2
```

Full example combining credentials, a local JMX upload, and test parameters:

```bash
python3 hyperexecute_automation.py \
  --username your_username \
  --api-key your_api_key \
  --project-id your_project_id \
  --upload-jmx /path/to/your/test-folder \
  --users 300 \
  --duration 250 \
  --rampup 60 \
  --jmx-path your-test-folder/your-test.jmx \
  --runtime java:11 \
  --region eastus
```

### Overriding JMeter properties with `--variable`

Pass `--variable KEY=VALUE` (repeatable) to override JMeter properties inside the JMX at runtime (`-J<key>=<value>`) - useful for JMX files that read values like `${__P(threads,1)}`:

```bash
python hyperexecute_automation.py \
  --jmx-path te22479.jmx \
  --variable threads=100 \
  --variable rampup=1 \
  --variable duration=1
```

## Step 7b: Running a Gatling test instead

Pass `--test-type gatling` and one of the three `--gatling-mode` load profiles. Each mode reads different parameters:

| `--gatling-mode` | Meaning | Required flags |
|---|---|---|
| `stress` | Ramps to a total number of injected users over the test duration | `--users` (total users), `--duration` |
| `capacity` | Ramps arrival rate from an initial to a final rate over the test duration | `--initial-users`, `--final-users`, `--duration` |
| `soak` | Holds a constant arrival rate for the full test duration | `--users` (rate/sec), `--duration` |

Just like `--upload-jmx`, `--upload-gatling` accepts a single simulation file or a whole project directory (uploaded recursively, preserving folder structure - use this for a full `src/test/java/...`-style package layout, which Gatling/Java requires):

```bash
# Stress: 10 total injected users over 120s
python hyperexecute_automation.py \
  --test-type gatling --gatling-mode stress \
  --users 10 --duration 120 \
  --upload-gatling ./gatling-project/ \
  --gatling-path gatling-project/src/test/java/example/BasicSimulation.java

# Capacity: ramp arrival rate from 1/s to 10/s over 120s
python hyperexecute_automation.py \
  --test-type gatling --gatling-mode capacity \
  --initial-users 1 --final-users 10 --duration 120 \
  --upload-gatling ./gatling-project/

# Soak: constant arrival rate of 5/s for 600s
python hyperexecute_automation.py \
  --test-type gatling --gatling-mode soak \
  --users 5 --duration 600 \
  --upload-gatling ./gatling-project/
```

If the upload returns a remote path, the script uses it automatically and `--gatling-path` is ignored - same behavior as `--upload-jmx`/`--jmx-path`.

## Sample commands

Quick-reference commands covering common argument combinations for both test types. All assume credentials are already set via environment variables (Step 4, Option A) unless shown otherwise.

### JMeter

```bash
# 1. Quick smoke test - just override the load profile, everything else defaults
python hyperexecute_automation.py --users 50 --duration 60 --rampup 20

# 2. Upload a local JMX + CSV data folder, override JMeter properties read via __P(), pick a region
python hyperexecute_automation.py \
  --upload-jmx ./test-plan/ \
  --variable threads=100 \
  --variable rampup=30 \
  --region eastus \
  --job-label "checkout-api-load"

# 3. CI-friendly run: explicit credentials, no zip download, verbose logs, auto-abort if the CI job is cancelled
python hyperexecute_automation.py \
  --username your_username \
  --api-key your_api_key \
  --project-id your_project_id \
  --users 300 \
  --duration 250 \
  --rampup 60 \
  --global-timeout 45 \
  --no-download \
  --debug \
  --abort-on-cancel
```

### Gatling

```bash
# 1. Stress: ramp to 10 total injected users over 120s, uploading the simulation project
python hyperexecute_automation.py \
  --test-type gatling --gatling-mode stress \
  --users 10 --duration 120 \
  --upload-gatling ./gatling-project/ \
  --gatling-path gatling-project/src/test/java/example/BasicSimulation.java

# 2. Capacity: ramp arrival rate from 1/s to 10/s over 120s, custom region + job label
python hyperexecute_automation.py \
  --test-type gatling --gatling-mode capacity \
  --initial-users 1 --final-users 10 --duration 120 \
  --upload-gatling ./gatling-project/ \
  --region eastus \
  --job-label "gatling-capacity-nightly"

# 3. Soak: constant 5/s arrival rate for 10 minutes, CI-friendly with auto-abort on cancel
python hyperexecute_automation.py \
  --test-type gatling --gatling-mode soak \
  --users 5 --duration 600 \
  --upload-gatling ./gatling-project/ \
  --global-timeout 30 \
  --no-download \
  --debug \
  --abort-on-cancel
```

Full option reference:

### Required (if not set via environment variables)

| Argument | Description |
|----------|-------------|
| `--username` | LambdaTest username (or `LT_USERNAME` env var) |
| `--api-key` | LambdaTest API key (or `LT_ACCESS_KEY` env var) |
| `--project-id` | HyperExecute Project ID (or `HYPEREXECUTE_PROJECT_ID` env var) |

### Test configuration

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--test-type` | str | `jmeter` | `jmeter` or `gatling` |
| `--users` | int | 100 | JMeter: number of users. Gatling `stress` mode: total injected users. Gatling `soak` mode: constant arrival rate/sec |
| `--duration` | int | 120 | Test duration in seconds |
| `--rampup` | int | 60 | Ramp-up period in seconds (JMeter only) |
| `--concurrency` | int | 1 | Job concurrency level |
| `--jmx-path` | str | `Ecommerce.jmx` | Path to the `.jmx` file inside the project workspace (or `HYPEREXECUTE_JMX_PATH` env var) |
| `--upload-jmx` | str | — | Local file or directory to upload before triggering the job |
| `--variable` | str | — | JMeter property override as `KEY=VALUE`, passed to the JMX as `-J<key>=<value>` (JMeter only). Repeatable |
| `--gatling-mode` | str | — | `stress`, `capacity`, or `soak` (required when `--test-type gatling`) |
| `--initial-users` | int | — | Starting arrival rate/sec (Gatling `capacity` mode only) |
| `--final-users` | int | — | Ending arrival rate/sec (Gatling `capacity` mode only) |
| `--gatling-path` | str | `BasicSimulation.java` | Path to the Gatling simulation file inside the project workspace |
| `--upload-gatling` | str | — | Local file or directory to upload before triggering the job |
| `--job-label` | str | auto-generated | Custom label shown on the HyperExecute dashboard |
| `--runtime` | str | `java:11` | Execution runtime as `language:version` |
| `--region` | str | platform/project default | HyperExecute region to run the job in (e.g. `eastus`) |
| `--global-timeout` | int | platform default (90m) | Overall job timeout in minutes. The script polls job status for this value plus 15 minutes before giving up client-side (see Troubleshooting) |

### Execution behavior

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--job-poll-interval` | int | 10 | Seconds between job status checks |
| `--artifact-poll-interval` | int | 10 | Seconds between artifact status checks |
| `--output` | str | auto-generated | Output filename for the downloaded artifact |
| `--no-download` | flag | off | Skip downloading artifacts (useful in CI/CD) |
| `--debug` | flag | off | Verbose output for troubleshooting |

Run `python hyperexecute_automation.py --help` to see this from the CLI.

## Step 8: Read the output

A successful run looks like this:

```
======================================================================
🚀 HyperExecute Automation Script
======================================================================
Configuration:
  - Username: your_username
  - Project ID: 01KCP1YBSJ09RVB765EWP0A83C
  - Users: 100
  - Duration: 120s
  - Ramp-up: 60s
  - Concurrency: 1
======================================================================

🔐 Initialized API client for user: your_username
🚀 Triggering job with users=100, duration=120s, rampup=60s...
✅ Job triggered successfully!
📋 Job ID: 617490e8-d30d-42ed-8be1-12d528f9598d

⏳ Waiting for job to start (VM provisioning)...
✅ VM provisioned! Job is now running.
✅ Job completed successfully!

📊 Job Summary:
   - Total Tasks: 1
   - Completed: 1
   - Failed: 0

📦 Monitoring artifact status (checking every 10s)...
✅ All artifacts are ready!

⬇️  Downloading artifact 'JMeter'...
✅ Artifact downloaded successfully!
📁 File: 617490e8-d30d-42ed-8be1-12d528f9598d_JMeter.zip

======================================================================
🎉 Workflow completed successfully!
======================================================================
```

Exit codes: `0` on success, `1` on failure at any stage (trigger, job monitoring, artifact monitoring, or download).

## Step 9 (optional): Use it in CI/CD

The script is designed to drop straight into a pipeline:

- **Exit codes**: `0` on success, `1` on failure at any stage — no extra handling needed beyond checking the process exit status.
- **`--no-download`**: skips the zip download when you only need pass/fail + the job ID (e.g. results are already visible on the HyperExecute dashboard).
- **`--debug`**: prints request/response detail so failures are diagnosable from build logs alone.
- **`--abort-on-cancel`**: on SIGINT/SIGTERM (e.g. the CI job/pipeline itself is cancelled), attempts to abort the in-progress HyperExecute job via the platform API before the process exits, instead of leaving it running orphaned on the dashboard. Opt-in (default off). Limitation: the job's numeric `jobNumber` must already be known, which happens after the first successful status poll — if the signal arrives before then (e.g. still uploading a file or the trigger call hasn't returned), there's nothing to abort yet and the script prints a warning telling you to cancel manually from the dashboard.
- **Secrets**: store `LT_USERNAME`, `LT_ACCESS_KEY`, and `HYPEREXECUTE_PROJECT_ID` as CI secrets/variables and export them as environment variables — never hardcode them in pipeline files.

```bash
python hyperexecute_automation.py \
  --users 100 \
  --duration 120 \
  --no-download \
  --debug \
  --abort-on-cancel
```

### GitHub Actions

```yaml
name: JMeter Performance Test
on: [workflow_dispatch]

jobs:
  run-jmeter:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.x'
      - run: pip install -r requirements.txt
      - name: Run HyperExecute JMeter job
        env:
          LT_USERNAME: ${{ secrets.LT_USERNAME }}
          LT_ACCESS_KEY: ${{ secrets.LT_ACCESS_KEY }}
          HYPEREXECUTE_PROJECT_ID: ${{ secrets.HYPEREXECUTE_PROJECT_ID }}
        run: |
          python hyperexecute_automation.py --users 100 --duration 120 --debug
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: jmeter-results
          path: '*_JMeter.zip'
```

### GitLab CI

```yaml
jmeter-test:
  image: python:3.11
  stage: test
  variables:
    LT_USERNAME: $LT_USERNAME
    LT_ACCESS_KEY: $LT_ACCESS_KEY
    HYPEREXECUTE_PROJECT_ID: $HYPEREXECUTE_PROJECT_ID
  script:
    - pip install -r requirements.txt
    - python hyperexecute_automation.py --users 100 --duration 120 --debug
  artifacts:
    when: always
    paths:
      - "*_JMeter.zip"
```

Set `LT_USERNAME`, `LT_ACCESS_KEY`, and `HYPEREXECUTE_PROJECT_ID` under **Settings → CI/CD → Variables** (masked/protected) rather than inline in the file.

### Jenkins (declarative pipeline)

```groovy
pipeline {
    agent any
    environment {
        LT_USERNAME             = credentials('lt-username')
        LT_ACCESS_KEY           = credentials('lt-access-key')
        HYPEREXECUTE_PROJECT_ID = credentials('hyperexecute-project-id')
    }
    stages {
        stage('Install') {
            steps { sh 'pip install -r requirements.txt' }
        }
        stage('Run JMeter Test') {
            steps {
                sh 'python hyperexecute_automation.py --users 100 --duration 120 --debug'
            }
        }
    }
    post {
        always {
            archiveArtifacts artifacts: '*_JMeter.zip', allowEmptyArchive: true
        }
    }
}
```

### Azure DevOps

```yaml
trigger: none

pool:
  vmImage: 'ubuntu-latest'

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.x'
  - script: pip install -r requirements.txt
    displayName: 'Install dependencies'
  - script: python hyperexecute_automation.py --users 100 --duration 120 --debug
    displayName: 'Run HyperExecute JMeter job'
    env:
      LT_USERNAME: $(LT_USERNAME)
      LT_ACCESS_KEY: $(LT_ACCESS_KEY)
      HYPEREXECUTE_PROJECT_ID: $(HYPEREXECUTE_PROJECT_ID)
  - task: PublishBuildArtifacts@1
    condition: always()
    inputs:
      pathToPublish: '.'
      artifactName: 'jmeter-results'
```

Define `LT_USERNAME`, `LT_ACCESS_KEY`, and `HYPEREXECUTE_PROJECT_ID` as secret pipeline variables in the Azure DevOps UI.

### CircleCI

```yaml
version: 2.1
jobs:
  jmeter-test:
    docker:
      - image: cimg/python:3.11
    steps:
      - checkout
      - run: pip install -r requirements.txt
      - run:
          name: Run HyperExecute JMeter job
          command: python hyperexecute_automation.py --users 100 --duration 120 --debug
      - store_artifacts:
          path: .
          destination: jmeter-results

workflows:
  jmeter:
    jobs:
      - jmeter-test
```

Set `LT_USERNAME`, `LT_ACCESS_KEY`, and `HYPEREXECUTE_PROJECT_ID` as CircleCI project environment variables (**Project Settings → Environment Variables**).

## Troubleshooting

**"Username is required" / similar errors**
Credentials weren't found. Provide them via `--username`/`--api-key`/`--project-id` or the `LT_USERNAME`/`LT_ACCESS_KEY`/`HYPEREXECUTE_PROJECT_ID` env vars.

**Authentication errors**
The script combines username and API key into a Basic Auth token automatically. Double-check you're using your **API key**, not your account password, and that the key has HyperExecute permissions.

**Job never completes**
Check the HyperExecute dashboard for the job ID printed in the output. Increase `--job-poll-interval` if you suspect API rate limiting, and confirm the JMeter test plan itself runs correctly outside of this script.

**Script exits with "Job did not complete successfully" but the job is still running on the dashboard**
This is a client-side polling timeout, not a job failure. The script only watches a job for `--global-timeout` plus 15 minutes (90m + 15m = 105m if `--global-timeout` isn't set) before giving up and exiting - it does not cancel the job, which keeps running on HyperExecute regardless. If your test genuinely needs longer than that to finish (long `--duration`, slow VM provisioning, etc.), pass a larger `--global-timeout` so the script's polling window scales with it.

**CI pipeline is cancelled but the HyperExecute job keeps running (orphaned)**
When a CI system kills this script's process (pipeline cancelled, job timed out, manually stopped in the CI UI), the script has no chance to clean up on its own, and the corresponding HyperExecute job is left running unattended. Pass `--abort-on-cancel` to have the script catch SIGINT/SIGTERM and call HyperExecute's abort API before exiting. Note this only works once the job's `jobNumber` is known (after the first status poll) - a cancellation that happens during file upload or immediately after triggering, before any status poll has completed, can't be auto-aborted and will need to be stopped manually from the dashboard.

**Download fails after a successful job**
Artifacts may still be processing — the script already waits for `completed` status, but very large reports can take longer than the default artifact timeout. Also check the artifact hasn't expired.

## Customizing the script

- **Artifact upload paths**: edit the `uploadArtefacts` list inside `trigger_job()` in [hyperexecute_automation.py](hyperexecute_automation.py).
- **Gatling injection types**: `trigger_gatling_job()` maps `--gatling-mode` to the platform's `injectionType` values via `HyperExecuteAPI.GATLING_INJECTION_TYPES`.
- **Timeouts**: `check_job_status()` and `check_artifact_status()` both accept a `max_wait_time` argument (seconds).
- **Extra headers**: add entries to `self.headers` in `HyperExecuteAPI.__init__`.

## License & Support

Provided as-is for use with the LambdaTest HyperExecute platform. For script issues, check the printed error messages and `--debug` output; for API/platform issues, refer to HyperExecute's API docs or LambdaTest support.
