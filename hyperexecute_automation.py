#!/usr/bin/env python3
"""
HyperExecute API Automation Script
Automates the workflow of:
1. Triggering a JMeter job
2. Monitoring job status until completion
3. Monitoring artifact status until completion
4. Downloading artifacts as a zip file
"""

import requests
import time
import json
import sys
import os
import signal
import base64
import mimetypes
from typing import Dict, Any, Optional, Tuple
import argparse

# Platform's own default job timeout (minutes) when --global-timeout isn't set,
# used to size the script's job-status polling ceiling (see main()).
DEFAULT_GLOBAL_TIMEOUT_MINUTES = 90


class HyperExecuteAPI:
    """Class to handle HyperExecute API operations"""
    
    def __init__(self, username: str, api_key: str, project_id: str):
        """
        Initialize the HyperExecute API client
        
        Args:
            username: LambdaTest username
            api_key: LambdaTest API key/access key
            project_id: Project ID for triggering jobs
        """
        self.username = username
        self.api_key = api_key
        self.project_id = project_id
        
        # Generate Basic Auth token from username and API key
        credentials = f"{username}:{api_key}"
        self.auth_token = base64.b64encode(credentials.encode()).decode()
        
        self.base_url_trigger = "https://api-hyperexecute.lambdatest.com"
        self.base_url_status = "https://api.hyperexecute.cloud"
        self.headers = {
            'accept': 'application/json',
            'Authorization': f'Basic {self.auth_token}',
            'content-type': 'application/json'
        }

        # Populated once a job's numeric jobNumber becomes known (see check_job_status);
        # used by abort_job() when --abort-on-cancel triggers on a CI cancellation signal.
        self.job_number: Optional[Any] = None

        print(f" Initialized API client for user: {username}")
        print(f" Generated Basic Auth token: {self.auth_token[:20]}...")

    def upload_file(self, local_path: str) -> Tuple[bool, Optional[str]]:
        """
        Upload a local file, or recursively upload every file in a local directory,
        to the HyperExecute project's file storage so it can be referenced by the
        trigger-job payload.

        A directory is uploaded as multiple 'files' parts in a single multipart
        request, one per file, with each part's filename prefixed by its path
        relative to the directory's parent - this is how the platform's own web
        UI preserves folder structure (there's no separate "directory" concept in
        the API itself).

        Args:
            local_path: Local path to a file or a directory to upload

        Returns:
            A (success, remote_path) tuple. success is True as long as the upload
            request returns a 2xx response - a missing remote_path in the response
            body does not count as a failure, it just means the caller should keep
            using whatever jmx_path it already had.
        """
        url = f"{self.base_url_trigger}/logistics/v1.0/project/{self.project_id}/files/upload"

        # No content-type header here: requests sets the multipart boundary itself
        upload_headers = {
            'accept': 'application/json, text/plain, */*',
            'authorization': f'Basic {self.auth_token}',
            'origin': 'https://hyperexecute.lambdatest.com'
        }

        if not os.path.exists(local_path):
            print(f"❌ Error: Path not found: {local_path}")
            return False, None

        # Build the list of (absolute_path, relative_name_sent_to_api) pairs
        if os.path.isdir(local_path):
            folder_name = os.path.basename(os.path.normpath(local_path))
            entries = []
            for root, _dirs, filenames in os.walk(local_path):
                for fn in filenames:
                    abs_path = os.path.join(root, fn)
                    rel_name = os.path.join(folder_name, os.path.relpath(abs_path, local_path))
                    entries.append((abs_path, rel_name.replace(os.sep, '/')))
            if not entries:
                print(f"❌ Error: No files found under directory: {local_path}")
                return False, None
        else:
            entries = [(local_path, os.path.basename(local_path))]

        opened_files = []
        try:
            print(f"\n⬆️  Uploading {len(entries)} file(s) from '{local_path}' "
                  f"to project {self.project_id}...")

            multipart_files = []
            for abs_path, rel_name in entries:
                print(f"   - {rel_name}")
                f = open(abs_path, 'rb')
                opened_files.append(f)
                content_type = mimetypes.guess_type(abs_path)[0] or 'application/octet-stream'
                multipart_files.append(('files', (rel_name, f, content_type)))

            response = requests.post(url, headers=upload_headers, files=multipart_files, timeout=120)

            print(f" Response Status: {response.status_code}")
            print(f" Response Body: {response.text[:500]}")

            response.raise_for_status()
            print(f"✅ Upload succeeded!")

            remote_path = None
            try:
                result = response.json()
                remote_path = result.get('path') or result.get('filePath')
                data_field = result.get('data')
                if not remote_path and isinstance(data_field, dict):
                    remote_path = data_field.get('path') or data_field.get('filePath')
                elif not remote_path and isinstance(data_field, list) and data_field:
                    first = data_field[0]
                    if isinstance(first, dict):
                        remote_path = first.get('path') or first.get('filePath') or first.get('name')
            except ValueError:
                pass  # response wasn't JSON - upload still succeeded on HTTP status alone

            if remote_path:
                print(f" Remote path: {remote_path}")
            else:
                print(f" ⚠️  Upload succeeded but no remote path found in response; "
                      f"will keep using the existing test file path")

            return True, remote_path

        except requests.exceptions.RequestException as e:
            print(f"❌ Error uploading: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"❌ Response Status: {e.response.status_code}")
                print(f"❌ Response Body: {e.response.text}")
            return False, None
        finally:
            for f in opened_files:
                f.close()

    def trigger_job(self, users: int, duration: int, rampup: int,
                   concurrency: int = 1, splitcsv: bool = False,
                   job_label: Optional[str] = None,
                   jmx_path: str = "hyperexecute-jmeter-/test.jmx",
                   runtime_language: str = "java", runtime_version: str = "11",
                   region: Optional[str] = None,
                   global_timeout: Optional[int] = None,
                   variables: Optional[Dict[str, str]] = None) -> Optional[str]:
        """
        Trigger a new JMeter job

        Args:
            users: Number of users for the JMeter test
            duration: Duration of the test in seconds
            rampup: Ramp-up period in seconds
            concurrency: Job concurrency level
            splitcsv: Whether to split CSV files
            job_label: Optional job label for dashboard display (auto-generated if not provided)
            jmx_path: Path to the .jmx file relative to the HyperExecute project workspace
            runtime_language: Language of the execution runtime (default: java)
            runtime_version: Version of the execution runtime (default: 11)
            region: Optional HyperExecute region to run the job in (e.g. eastus)
            global_timeout: Optional overall job timeout in minutes
            variables: Optional JMeter property overrides (e.g. {"threads": "100"}),
                passed through to the JMX as -J<key>=<value>

        Returns:
            Job ID if successful, None otherwise

        Note:
            This method automatically enables JMeter HTML report generation (-e -o report)
            which is required for dashboard data visualization. The report includes test
            metrics, graphs, and statistics that appear in the HyperExecute dashboard.
        """
        url = f"{self.base_url_trigger}/reception/api/project/{self.project_id}/trigger-job"
        
        # Headers specific for trigger API (matching Postman exactly)
        trigger_headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': f'Basic {self.auth_token}',
            'content-type': 'application/json',
            'origin': 'https://hyperexecute.lambdatest.com'
        }
        
        # Generate a meaningful label if not provided
        # This helps the dashboard display and filter jobs properly
        if job_label is None:
            job_label = f"JMeter-{users}users-{duration}s-{rampup}s-rampup"
        
        jmeter_config = {
            "users": users,
            "duration": duration,
            "rampup": rampup,
            "splitcsv": splitcsv,
            # CRITICAL: These args generate HTML report dashboard with test data
            # -e: generate HTML report dashboard
            # -o: output directory flag
            # report: output directory name
            # Without these, the dashboard will have no data to display
            "args": ["-e", "-o", "report"],
            "jmx": jmx_path
        }
        if region:
            jmeter_config["region"] = region
        if variables:
            jmeter_config["variables"] = variables

        payload = {
            "jmeter": [jmeter_config],
            "jobLabel": [job_label],  # Fixed: Added meaningful label for dashboard visibility
            "concurrency": concurrency,
            "runtime": [
                {
                    "language": runtime_language,
                    "version": runtime_version
                }
            ],
            "uploadArtefacts": [
                {
                    "name": "JMeter",  # Fixed: Changed to "JMeter" to match dashboard artifact expectations
                    "path": [
                        "*.jtl",  # JMeter test log files (raw test data - required for dashboard)
                        "*.csv",  # CSV result files
                        "result.csv",  # Specific result file
                        "report/**/*"  # All files in report directory (HTML, JSON, CSS, etc.)
                    ]
                }
            ]
        }
        if global_timeout is not None:
            payload["globalTimeout"] = global_timeout

        try:
            print(f"🚀 Triggering job with users={users}, duration={duration}s, rampup={rampup}s...")
            print(f" URL: {url}")
            print(f" Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(url, headers=trigger_headers, json=payload, timeout=30)
            
            print(f" Response Status: {response.status_code}")
            print(f" Response Body: {response.text[:500]}")  # First 500 chars
            
            response.raise_for_status()
            
            result = response.json()
            job_id = result.get('jobId') or result.get('jobID')
            
            if result.get('status') == 'success' and job_id:
                print(f"✅ Job triggered successfully!")
                print(f" Job ID: {job_id}")
                print(f" Org ID: {result.get('orgID')}")
                return job_id
            else:
                print(f"❌ Failed to trigger job: {result}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Error triggering job: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"❌ Response Status: {e.response.status_code}")
                print(f"❌ Response Body: {e.response.text}")
            return None

    # Maps our --gatling-mode CLI values to the injectionType string the
    # runner needs to hit the right Gatling load-profile branch. Verified
    # against a live trigger-job sweep - "capacityTest"/"soakTest" literal
    # strings route to a different (closed-model) profile that ignores
    # initial/final-user and rate overrides, so the ramp/constant-rate
    # variants have to be requested via these values instead.
    GATLING_INJECTION_TYPES = {
        "stress": "stressPeakUsers",
        "capacity": "rampUsersPerSec",
        "soak": "constantUsersPerSec",
    }

    def trigger_gatling_job(self, gatling_mode: str, duration: int,
                           users: Optional[int] = None,
                           initial_users: Optional[int] = None,
                           final_users: Optional[int] = None,
                           concurrency: int = 1, splitcsv: bool = False,
                           job_label: Optional[str] = None,
                           filepath: str = "BasicSimulation.java",
                           runtime_language: str = "java", runtime_version: str = "11",
                           region: Optional[str] = None,
                           global_timeout: Optional[int] = None) -> Optional[str]:
        """
        Trigger a new Gatling job

        Args:
            gatling_mode: One of "stress", "capacity", "soak" - selects the injectionType
                and which of users/initial_users/final_users are required
            duration: Duration of the test in seconds (all modes)
            users: Total injected users (stress mode) or constant arrival rate per
                second (soak mode)
            initial_users: Starting arrival rate per second (capacity mode)
            final_users: Ending arrival rate per second (capacity mode)
            concurrency: Job concurrency level
            splitcsv: Whether to split CSV files
            job_label: Optional job label for dashboard display (auto-generated if not provided)
            filepath: Path to the Gatling simulation file relative to the HyperExecute
                project workspace (or the path returned by uploading one)
            runtime_language: Language of the execution runtime (default: java)
            runtime_version: Version of the execution runtime (default: 11)
            region: Optional HyperExecute region to run the job in (e.g. eastus)
            global_timeout: Optional overall job timeout in minutes

        Returns:
            Job ID if successful, None otherwise
        """
        if gatling_mode not in self.GATLING_INJECTION_TYPES:
            print(f"❌ Error: --gatling-mode must be one of {list(self.GATLING_INJECTION_TYPES)}, "
                  f"got '{gatling_mode}'")
            return None

        gatling_config = {
            "duration": duration,
            "splitcsv": splitcsv,
            "injectionType": self.GATLING_INJECTION_TYPES[gatling_mode],
            "filepath": filepath,
        }

        if gatling_mode == "stress":
            if users is None:
                print("❌ Error: --users is required for --gatling-mode stress")
                return None
            gatling_config["users"] = users
        elif gatling_mode == "capacity":
            if initial_users is None or final_users is None:
                print("❌ Error: --initial-users and --final-users are required for --gatling-mode capacity")
                return None
            gatling_config["usersStart"] = initial_users
            gatling_config["usersEnd"] = final_users
        elif gatling_mode == "soak":
            if users is None:
                print("❌ Error: --users is required for --gatling-mode soak (used as the constant arrival rate)")
                return None
            gatling_config["users"] = users

        if region:
            gatling_config["region"] = region

        if job_label is None:
            job_label = f"Gatling-{gatling_mode}-{duration}s"

        url = f"{self.base_url_trigger}/reception/api/project/{self.project_id}/trigger-job"
        trigger_headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': f'Basic {self.auth_token}',
            'content-type': 'application/json',
            'origin': 'https://hyperexecute.lambdatest.com'
        }

        payload = {
            "gatling": [gatling_config],
            "jobLabel": [job_label],
            "concurrency": concurrency,
            "runtime": [
                {
                    "language": runtime_language,
                    "version": runtime_version
                }
            ],
        }
        if global_timeout is not None:
            payload["globalTimeout"] = global_timeout

        try:
            print(f"🚀 Triggering Gatling {gatling_mode} job (duration={duration}s)...")
            print(f" URL: {url}")
            print(f" Payload: {json.dumps(payload, indent=2)}")

            response = requests.post(url, headers=trigger_headers, json=payload, timeout=30)

            print(f" Response Status: {response.status_code}")
            print(f" Response Body: {response.text[:500]}")

            response.raise_for_status()

            result = response.json()
            job_id = result.get('jobId') or result.get('jobID')

            if result.get('status') == 'success' and job_id:
                print(f"✅ Job triggered successfully!")
                print(f" Job ID: {job_id}")
                print(f" Org ID: {result.get('orgID')}")
                return job_id
            else:
                print(f"❌ Failed to trigger job: {result}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"❌ Error triggering job: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"❌ Response Status: {e.response.status_code}")
                print(f"❌ Response Body: {e.response.text}")
            return None

    def check_job_status(self, job_id: str, poll_interval: int = 10,
                        max_wait_time: int = 3600) -> bool:
        """
        Monitor job status until completion
        
        Args:
            job_id: The job ID to monitor
            poll_interval: Time in seconds between status checks
            max_wait_time: Maximum time to wait in seconds
            
        Returns:
            True if job completed successfully, False otherwise
        """
        url = f"{self.base_url_status}/v2.0/job/{job_id}"
        
        print(f"\n⏳ Waiting for job to start (VM provisioning)...")
        start_time = time.time()
        vm_start_time = None
        job_started = False
        
        while True:
            try:
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                
                result = response.json()
                data = result.get('data', {})
                if data.get('jobNumber') is not None:
                    self.job_number = data.get('jobNumber')
                status = data.get('status')
                
                elapsed_time = int(time.time() - start_time)
                
                # Wait for 'running' status before starting detailed monitoring
                if not job_started:
                    if status == 'initiated':
                        # Just show we're waiting for VM
                        if elapsed_time % 30 == 0 or elapsed_time < 5:  # Print every 30s or initially
                            print(f"⏱️  [{elapsed_time}s] VM provisioning in progress (status: initiated)...")
                    elif status == 'running':
                        vm_start_time = time.time()
                        job_started = True
                        print(f"✅ VM provisioned! Job is now running.")
                        print(f" Monitoring test execution (checking every {poll_interval}s)...")
                    elif status == 'completed':
                        print(f"✅ Job completed successfully!")
                        self._display_job_summary(data, result)
                        return True
                    elif status in ['failed', 'cancelled', 'aborted', 'timeout']:
                        print(f"❌ Job ended with status: {status} during VM provisioning")
                        return False
                else:
                    # Job is running - show detailed progress
                    test_elapsed = int(time.time() - vm_start_time) if vm_start_time else 0
                    print(f"⏱️  [Test running for {test_elapsed}s] Job status: {status}")
                    
                    if status == 'completed':
                        print(f"✅ Job completed successfully!")
                        self._display_job_summary(data, result)
                        return True
                        
                    elif status in ['failed', 'cancelled', 'aborted', 'timeout']:
                        print(f"❌ Job ended with status: {status}")
                        self._display_job_summary(data, result)
                        return False
                
                # Check overall timeout
                if elapsed_time > max_wait_time:
                    print(f"⏱️  Timeout: Job did not complete within {max_wait_time}s")
                    return False
                
                time.sleep(poll_interval)
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Error checking job status: {e}")
                return False
    
    def _display_job_summary(self, data: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Helper method to display job summary"""
        task_count = data.get('taskCount', {})
        print(f"\n📊 Job Summary:")
        print(f"   - Job Number: {data.get('jobNumber')}")
        print(f"   - Start Time: {data.get('startTime')}")
        print(f"   - End Time: {data.get('endTime')}")
        print(f"   - Total Tasks: {task_count.get('total', 0)}")
        print(f"   - Completed: {task_count.get('completed', 0)}")
        print(f"   - Failed: {task_count.get('failed', 0)}")
        print(f"   - Execution Time: {result.get('executionTime', 'N/A')}")
    
    def check_artifact_status(self, job_id: str, poll_interval: int = 10, 
                             max_wait_time: int = 600) -> bool:
        """
        Monitor artifact status until completion
        
        Args:
            job_id: The job ID to check artifacts for
            poll_interval: Time in seconds between status checks
            max_wait_time: Maximum time to wait in seconds
            
        Returns:
            True if artifacts are ready, False otherwise
        """
        url = f"{self.base_url_status}/v2.0/job/{job_id}/artefacts"
        
        print(f"\n Monitoring artifact status (checking every {poll_interval}s)...")
        start_time = time.time()
        
        while True:
            try:
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                
                result = response.json()
                artifacts = result.get('data', [])
                
                elapsed_time = int(time.time() - start_time)
                
                if not artifacts:
                    print(f"⏱️  [{elapsed_time}s] No artifacts found yet...")
                else:
                    all_completed = True
                    for artifact in artifacts:
                        status = artifact.get('status')
                        name = artifact.get('name')
                        size = artifact.get('size')
                        
                        print(f"⏱️  [{elapsed_time}s] Artifact '{name}': {status} (size: {size} bytes)")
                        
                        if status != 'completed':
                            all_completed = False
                    
                    if all_completed:
                        print(f"✅ All artifacts are ready!")
                        
                        # Display artifact details
                        print(f"\n📋 Artifact Details:")
                        for artifact in artifacts:
                            print(f"   - Name: {artifact.get('name')}")
                            print(f"   - ID: {artifact.get('id')}")
                            print(f"   - Size: {artifact.get('size')} bytes")
                            print(f"   - Created: {artifact.get('createdAt')}")
                            print(f"   - Expiry: {artifact.get('expiry')}")
                        
                        return True
                
                if elapsed_time > max_wait_time:
                    print(f"⏱️  Timeout: Artifacts did not complete within {max_wait_time}s")
                    return False
                
                time.sleep(poll_interval)
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Error checking artifact status: {e}")
                return False
    
    def download_artifact(self, job_id: str, artifact_name: str = "JMeter", 
                         output_filename: Optional[str] = None) -> bool:
        """
        Download artifacts as a zip file
        
        Args:
            job_id: The job ID to download artifacts for
            artifact_name: Name of the artifact to download
            output_filename: Optional output filename (defaults to <job_id>_<artifact_name>.zip)
            
        Returns:
            True if download successful, False otherwise
        """
        url = f"{self.base_url_status}/v2.0/artefacts/{job_id}/download?name={artifact_name}"
        
        if output_filename is None:
            output_filename = f"{job_id}_{artifact_name}.zip"
        
        try:
            print(f"\n⬇️  Downloading artifact '{artifact_name}'...")
            
            response = requests.get(url, headers=self.headers, stream=True)
            response.raise_for_status()
            
            # Save the file
            file_size = 0
            with open(output_filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    file_size += len(chunk)

            print(f"✅ Artifact downloaded successfully!")
            print(f"📁 File: {output_filename}")
            print(f"📊 Size: {file_size:,} bytes ({file_size / 1024:.2f} KB)")
            
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error downloading artifact: {e}")
            if hasattr(e.response, 'text'):
                print(f"Response: {e.response.text}")
            return False

    def abort_job(self, job_number: Any) -> bool:
        """
        Abort an in-progress HyperExecute job by its numeric jobNumber.

        Args:
            job_number: The numeric jobNumber (not the job_id UUID) obtained from
                a prior check_job_status() poll (self.job_number).

        Returns:
            True if the abort request was accepted, False otherwise.
        """
        url = f"{self.base_url_status}/v1.0/job/{job_number}/abort"

        try:
            print(f"\n🛑 Requesting abort for job number {job_number}...")
            # Kept short: called from a signal handler racing a CI runner's
            # cancellation grace period (e.g. GitHub Actions force-kills the
            # process a few seconds after SIGTERM), so we can't afford to block long.
            response = requests.put(url, headers=self.headers, timeout=8)
            response.raise_for_status()
            print(f"✅ Abort request accepted for job number {job_number}.")
            return True
        except requests.exceptions.RequestException as e:
            print(f"❌ Error aborting job {job_number}: {e}")
            if hasattr(e, 'response') and e.response is not None and hasattr(e.response, 'text'):
                print(f"Response: {e.response.text}")
            return False


def main():
    """Main function to run the automation workflow"""
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Automate HyperExecute JMeter job execution and artifact download',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with username and API key
  python hyperexecute_automation.py --username myuser --api-key mykey123 --project-id PROJECT123

  # With custom test parameters
  python hyperexecute_automation.py --username myuser --api-key mykey123 --project-id PROJECT123 --users 200 --duration 300

  # Using environment variables
  export LT_USERNAME=myuser
  export LT_ACCESS_KEY=mykey123
  export HYPEREXECUTE_PROJECT_ID=PROJECT123
  python hyperexecute_automation.py
        """
    )

    # Required credentials
    parser.add_argument('--username', type=str,
                       default=None,
                       help='LambdaTest username (or set LT_USERNAME env var)')
    parser.add_argument('--api-key', type=str,
                       default=None,
                       help='LambdaTest access key (or set LT_ACCESS_KEY env var)')
    parser.add_argument('--project-id', type=str, 
                       default=None,
                       help='HyperExecute Project ID (or set HYPEREXECUTE_PROJECT_ID env var)')
    
    # Test type
    parser.add_argument('--test-type', type=str, choices=['jmeter', 'gatling'], default='jmeter',
                       help='Which load testing tool to trigger (default: jmeter)')

    # Test parameters
    parser.add_argument('--users', type=int, default=100,
                       help='Number of users. For JMeter this is the JMeter test user count. '
                            'For Gatling: total injected users in --gatling-mode stress, or the '
                            'constant arrival rate/sec in --gatling-mode soak (default: 100)')
    parser.add_argument('--duration', type=int, default=120,
                       help='Test duration in seconds (default: 120)')
    parser.add_argument('--rampup', type=int, default=60,
                       help='Ramp-up period in seconds (JMeter only, default: 60)')
    parser.add_argument('--concurrency', type=int, default=1,
                       help='Job concurrency level (default: 1)')
    parser.add_argument('--gatling-mode', type=str, choices=['stress', 'capacity', 'soak'], default=None,
                       help='Gatling load profile (required when --test-type gatling): '
                            '"stress" ramps to --users total injected users over --duration; '
                            '"capacity" ramps arrival rate from --initial-users to --final-users '
                            'over --duration; "soak" holds a constant arrival rate of --users/sec '
                            'for --duration')
    parser.add_argument('--initial-users', type=int, default=None,
                       help='Starting arrival rate per second (Gatling --gatling-mode capacity only)')
    parser.add_argument('--final-users', type=int, default=None,
                       help='Ending arrival rate per second (Gatling --gatling-mode capacity only)')
    parser.add_argument('--job-poll-interval', type=int, default=10,
                       help='Job status polling interval in seconds (default: 10)')
    parser.add_argument('--artifact-poll-interval', type=int, default=10,
                       help='Artifact status polling interval in seconds (default: 10)')
    parser.add_argument('--output', type=str, default=None,
                       help='Output filename for downloaded artifact (default: auto-generated)')
    parser.add_argument('--job-label', type=str, default=None,
                       help='Custom job label for dashboard display (default: auto-generated from test parameters)')
    parser.add_argument('--jmx-path', type=str, default='hyperexecute-jmeter-/test.jmx',
                       help='Path to the .jmx file relative to the HyperExecute project workspace '
                            '(or set HYPEREXECUTE_JMX_PATH env var; default: hyperexecute-jmeter-/test.jmx). '
                            'Ignored if --upload-jmx is used and the upload returns a remote path.')
    parser.add_argument('--upload-jmx', type=str, default=None,
                       help='Local path to a .jmx file, or a directory (uploaded recursively, '
                            'preserving folder structure - e.g. for .jmx + CSV data files), to '
                            'upload to the HyperExecute project before triggering the job '
                            '(e.g. --upload-jmx ./test.jmx or --upload-jmx ./test-plan/)')
    parser.add_argument('--variable', action='append', default=[], metavar='KEY=VALUE',
                       help='JMeter property override, passed through to the JMX as -J<key>=<value> '
                            '(JMeter only). Repeatable: --variable threads=100 --variable rampup=1')
    parser.add_argument('--gatling-path', type=str, default='BasicSimulation.java',
                       help='Path to the Gatling simulation file relative to the HyperExecute '
                            'project workspace (default: BasicSimulation.java). Ignored if '
                            '--upload-gatling is used and the upload returns a remote path.')
    parser.add_argument('--upload-gatling', type=str, default=None,
                       help='Local path to a Gatling simulation file, or a project directory '
                            '(uploaded recursively, preserving folder structure - e.g. for the '
                            'full src/test/java/... package layout), to upload to the '
                            'HyperExecute project before triggering the job '
                            '(e.g. --upload-gatling ./gatling-project/)')
    parser.add_argument('--runtime', type=str, default='java:11',
                       help='Execution runtime as language:version (default: java:11)')
    parser.add_argument('--region', type=str, default=None,
                       help='HyperExecute region to run the job in (e.g. eastus). Uses the '
                            'project/account default region if not set')
    parser.add_argument('--global-timeout', type=int, default=None,
                       help='Overall job timeout in minutes. Uses the platform default if not set')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode with verbose output for CI/CD troubleshooting')
    parser.add_argument('--no-download', action='store_true',
                       help='Skip artifact download (useful for CI/CD where you just need job completion)')
    parser.add_argument('--abort-on-cancel', action='store_true',
                       help='If the script receives SIGINT/SIGTERM (e.g. the CI job is cancelled), '
                            'attempt to abort the in-progress HyperExecute job via the platform API '
                            'before exiting, instead of leaving it running orphaned. Opt-in, default off. '
                            'No effect if triggered before the first status poll (jobNumber not yet known).')

    args = parser.parse_args()
    
    # Get credentials from arguments or environment variables
    import os
    username = args.username or os.environ.get('LT_USERNAME') or os.environ.get('LAMBDATEST_USERNAME')
    api_key = args.api_key or os.environ.get('LT_ACCESS_KEY') or os.environ.get('LAMBDATEST_API_KEY')
    project_id = args.project_id or os.environ.get('HYPEREXECUTE_PROJECT_ID')
    jmx_path = args.jmx_path or os.environ.get('HYPEREXECUTE_JMX_PATH', 'hyperexecute-jmeter-/test.jmx')
    gatling_path = args.gatling_path

    # Validate required credentials
    if not username:
        print("❌ Error: Username is required. Provide via --username or LT_USERNAME env var")
        sys.exit(1)

    if not api_key:
        print("❌ Error: API key is required. Provide via --api-key or LT_ACCESS_KEY env var")
        sys.exit(1)

    if not project_id:
        print("❌ Error: Project ID is required. Provide via --project-id or HYPEREXECUTE_PROJECT_ID env var")
        sys.exit(1)

    if args.test_type == 'gatling' and args.gatling_mode is None:
        print("❌ Error: --gatling-mode is required when --test-type gatling "
              "(one of: stress, capacity, soak)")
        sys.exit(1)

    # Parse --runtime into language/version
    if ':' not in args.runtime:
        print(f"❌ Error: --runtime must be in language:version format (e.g. java:11), got '{args.runtime}'")
        sys.exit(1)
    runtime_language, runtime_version = args.runtime.split(':', 1)

    # Parse --variable KEY=VALUE entries into a dict
    variables = {}
    for entry in args.variable:
        if '=' not in entry:
            print(f"❌ Error: --variable must be in KEY=VALUE format, got '{entry}'")
            sys.exit(1)
        key, value = entry.split('=', 1)
        variables[key] = value

    # Generate job label for display (will be used in the trigger call if not provided)
    if args.job_label is not None:
        job_label_display = args.job_label
    elif args.test_type == 'gatling':
        job_label_display = f"Gatling-{args.gatling_mode}-{args.duration}s"
    else:
        job_label_display = f"JMeter-{args.users}users-{args.duration}s-{args.rampup}s-rampup"

    print("=" * 70)
    print("🚀 HyperExecute Automation Script")
    if args.debug:
        print("🐛 DEBUG MODE ENABLED")
    print("=" * 70)
    print(f"Configuration:")
    print(f"  - Username: {username}")
    print(f"  - Project ID: {project_id}")
    print(f"  - Test Type: {args.test_type}")
    if args.test_type == 'gatling':
        print(f"  - Gatling Mode: {args.gatling_mode}")
        if args.gatling_mode == 'capacity':
            print(f"  - Initial Users: {args.initial_users}")
            print(f"  - Final Users: {args.final_users}")
        else:
            print(f"  - Users: {args.users}")
        print(f"  - Duration: {args.duration}s")
        print(f"  - Gatling Path: {gatling_path}")
    else:
        print(f"  - Users: {args.users}")
        print(f"  - Duration: {args.duration}s")
        print(f"  - Ramp-up: {args.rampup}s")
        print(f"  - JMX Path: {jmx_path}")
        if variables:
            print(f"  - Variables: {variables}")
    print(f"  - Concurrency: {args.concurrency}")
    print(f"  - Job Label: {job_label_display}")
    print(f"  - Runtime: {runtime_language}:{runtime_version}")
    if args.region:
        print(f"  - Region: {args.region}")
    if args.global_timeout is not None:
        print(f"  - Global Timeout: {args.global_timeout}m")
    if args.debug:
        print(f"  - Debug Mode: ON")
        print(f"  - Skip Download: {args.no_download}")
        print(f"  - Abort on Cancel: {args.abort_on_cancel}")
    print("=" * 70 + "\n")

    # Initialize API client
    api = HyperExecuteAPI(username, api_key, project_id)

    if args.abort_on_cancel:
        abort_state = {'in_progress': False}

        def _handle_cancel_signal(signum, frame):
            if abort_state['in_progress']:
                return
            abort_state['in_progress'] = True
            sig_name = signal.Signals(signum).name
            print(f"\n🛑 Received {sig_name}. Attempting to abort HyperExecute job before exiting...", flush=True)
            if api.job_number is None:
                print("⚠️  No jobNumber known yet - cannot auto-abort. "
                      "Cancel manually from the HyperExecute dashboard if a job was triggered.", flush=True)
            else:
                api.abort_job(api.job_number)
            sys.stdout.flush()
            sys.exit(128 + signum)

        signal.signal(signal.SIGINT, _handle_cancel_signal)
        signal.signal(signal.SIGTERM, _handle_cancel_signal)

    if args.test_type == 'gatling':
        # Step 0 (optional): Upload a local Gatling file/project to the project before triggering
        if args.upload_gatling:
            upload_success, uploaded_path = api.upload_file(args.upload_gatling)
            if not upload_success:
                print("\n❌ Failed to upload Gatling file. Exiting.")
                if args.debug:
                    print("🐛 Debug Info: Check the response body above for API errors")
                sys.exit(1)
            if uploaded_path:
                gatling_path = uploaded_path
                print(f" Using uploaded Gatling path: {gatling_path}")
            else:
                print(f" Upload succeeded (200 OK); continuing with Gatling path: {gatling_path}")

        # Step 1: Trigger the job
        job_id = api.trigger_gatling_job(
            gatling_mode=args.gatling_mode,
            duration=args.duration,
            users=args.users,
            initial_users=args.initial_users,
            final_users=args.final_users,
            concurrency=args.concurrency,
            job_label=args.job_label,
            filepath=gatling_path,
            runtime_language=runtime_language,
            runtime_version=runtime_version,
            region=args.region,
            global_timeout=args.global_timeout
        )
    else:
        # Step 0 (optional): Upload a local .jmx file to the project before triggering
        if args.upload_jmx:
            upload_success, uploaded_path = api.upload_file(args.upload_jmx)
            if not upload_success:
                print("\n❌ Failed to upload JMX file. Exiting.")
                if args.debug:
                    print("🐛 Debug Info: Check the response body above for API errors")
                sys.exit(1)
            if uploaded_path:
                jmx_path = uploaded_path
                print(f" Using uploaded JMX path: {jmx_path}")
            else:
                print(f" Upload succeeded (200 OK); continuing with JMX path: {jmx_path}")

        # Step 1: Trigger the job
        job_id = api.trigger_job(
            users=args.users,
            duration=args.duration,
            rampup=args.rampup,
            concurrency=args.concurrency,
            job_label=args.job_label,
            jmx_path=jmx_path,
            runtime_language=runtime_language,
            runtime_version=runtime_version,
            region=args.region,
            global_timeout=args.global_timeout,
            variables=variables
        )

    if not job_id:
        print("\n❌ Failed to trigger job. Exiting.")
        if args.debug:
            print("🐛 Debug Info: Check the response body above for API errors")
        sys.exit(1)
    
    # Step 2: Monitor job status
    # The script's own polling ceiling is independent of --global-timeout (which the
    # platform enforces server-side) - poll 15 minutes past whatever globalTimeout was
    # requested (or the platform's own 90-minute default, if none was given) so the
    # script doesn't give up watching before the platform would have force-stopped the
    # job itself.
    effective_global_timeout = args.global_timeout if args.global_timeout is not None else DEFAULT_GLOBAL_TIMEOUT_MINUTES
    job_max_wait = (effective_global_timeout + 15) * 60
    job_completed = api.check_job_status(
        job_id=job_id,
        poll_interval=args.job_poll_interval,
        max_wait_time=job_max_wait
    )
    
    if not job_completed:
        print("\n❌ Job did not complete successfully. Exiting.")
        if args.debug:
            print(f"🐛 Debug Info: Job ID {job_id} - Check HyperExecute dashboard for details")
        sys.exit(1)
    
    # Step 3: Monitor artifact status
    artifacts_ready = api.check_artifact_status(
        job_id=job_id,
        poll_interval=args.artifact_poll_interval
    )
    
    if not artifacts_ready:
        print("\n❌ Artifacts not ready. Exiting.")
        if args.debug:
            print(f"🐛 Debug Info: Job ID {job_id} - Artifacts may still be processing")
        sys.exit(1)
    
    # Step 4: Download artifacts (optional in CI/CD)
    if args.no_download:
        print("\n⏭️  Skipping artifact download (--no-download flag set)")
        print("📋 Artifacts are ready but not downloaded")
        print(f"🔗 Job ID: {job_id}")
        print(f"🔗 View in dashboard: https://hyperexecute.lambdatest.com/hyperexecute/jobs/{job_id}")
    else:
        download_success = api.download_artifact(
            job_id=job_id,
            artifact_name="Gatling" if args.test_type == 'gatling' else "JMeter",
            output_filename=args.output
        )
        
        if not download_success:
            print("\n❌ Failed to download artifacts. Exiting.")
            if args.debug:
                print(f"🐛 Debug Info: Job ID {job_id} - Download failed, but job completed successfully")
                print(f"🐛 You can manually download from: https://hyperexecute.lambdatest.com/hyperexecute/jobs/{job_id}")
            sys.exit(1)
    
    print("\n" + "=" * 70)
    print("🎉 Workflow completed successfully!")
    print(f"📋 Job ID: {job_id}")
    if args.debug:
        print(f"🐛 Debug: All steps completed successfully")
    print("=" * 70)


if __name__ == "__main__":
    main()
