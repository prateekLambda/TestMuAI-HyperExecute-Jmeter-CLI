# HyperExecute Automation Script

A Python script that automates running a JMeter performance test on LambdaTest HyperExecute: it triggers the job, monitors it to completion, waits for artifacts to be ready, and downloads the results as a zip file.

Follow the steps below in order to go from a clean checkout to a downloaded test report.

## Step 1: Check prerequisites

- Python 3.7+
- A LambdaTest account with access to HyperExecute
- A HyperExecute project already set up with a `.jmx` test plan (either already in the project workspace, or on your local machine to upload in Step 4)

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

- **Already uploaded to the project workspace?** Pass its path with `--jmx-path` (or set `HYPEREXECUTE_JMX_PATH`). Default: `hyperexecute-jmeter-/test.jmx`.
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
  --jmx-path your-test-folder/your-test.jmx
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
| `--users` | int | 100 | Number of users for the JMeter test |
| `--duration` | int | 120 | Test duration in seconds |
| `--rampup` | int | 60 | Ramp-up period in seconds |
| `--concurrency` | int | 1 | Job concurrency level |
| `--jmx-path` | str | `hyperexecute-jmeter-/test.jmx` | Path to the `.jmx` file inside the project workspace (or `HYPEREXECUTE_JMX_PATH` env var) |
| `--upload-jmx` | str | — | Local file or directory to upload before triggering the job |
| `--job-label` | str | auto-generated | Custom label shown on the HyperExecute dashboard |

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
- **Secrets**: store `LT_USERNAME`, `LT_ACCESS_KEY`, and `HYPEREXECUTE_PROJECT_ID` as CI secrets/variables and export them as environment variables — never hardcode them in pipeline files.

```bash
python hyperexecute_automation.py \
  --users 100 \
  --duration 120 \
  --no-download \
  --debug
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

**Download fails after a successful job**
Artifacts may still be processing — the script already waits for `completed` status, but very large reports can take longer than the default artifact timeout. Also check the artifact hasn't expired.

## Customizing the script

- **Artifact upload paths**: edit the `uploadArtefacts` list inside `trigger_job()` in [hyperexecute_automation.py](hyperexecute_automation.py).
- **Timeouts**: `check_job_status()` and `check_artifact_status()` both accept a `max_wait_time` argument (seconds).
- **Extra headers**: add entries to `self.headers` in `HyperExecuteAPI.__init__`.

## License & Support

Provided as-is for use with the LambdaTest HyperExecute platform. For script issues, check the printed error messages and `--debug` output; for API/platform issues, refer to HyperExecute's API docs or LambdaTest support.
