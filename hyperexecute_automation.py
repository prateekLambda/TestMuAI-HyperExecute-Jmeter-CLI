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
import base64
import mimetypes
from typing import Dict, Any, Optional, Tuple
import argparse


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
                      f"will keep using the existing --jmx-path value")

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
                   jmx_path: str = "hyperexecute-jmeter-/test.jmx") -> Optional[str]:
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
        
        payload = {
            "jmeter": [
                {
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
            ],
            "jobLabel": [job_label],  # Fixed: Added meaningful label for dashboard visibility
            "concurrency": concurrency,
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
            with open(output_filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            file_size = len(response.content)
            print(f"✅ Artifact downloaded successfully!")
            print(f"📁 File: {output_filename}")
            print(f"📊 Size: {file_size:,} bytes ({file_size / 1024:.2f} KB)")
            
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error downloading artifact: {e}")
            if hasattr(e.response, 'text'):
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
    
    # Test parameters
    parser.add_argument('--users', type=int, default=100,
                       help='Number of users for JMeter test (default: 100)')
    parser.add_argument('--duration', type=int, default=120,
                       help='Test duration in seconds (default: 120)')
    parser.add_argument('--rampup', type=int, default=60,
                       help='Ramp-up period in seconds (default: 60)')
    parser.add_argument('--concurrency', type=int, default=1,
                       help='Job concurrency level (default: 1)')
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
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode with verbose output for CI/CD troubleshooting')
    parser.add_argument('--no-download', action='store_true',
                       help='Skip artifact download (useful for CI/CD where you just need job completion)')
    
    args = parser.parse_args()
    
    # Get credentials from arguments or environment variables
    import os
    username = args.username or os.environ.get('LT_USERNAME') or os.environ.get('LAMBDATEST_USERNAME')
    api_key = args.api_key or os.environ.get('LT_ACCESS_KEY') or os.environ.get('LAMBDATEST_API_KEY')
    project_id = args.project_id or os.environ.get('HYPEREXECUTE_PROJECT_ID')
    jmx_path = args.jmx_path or os.environ.get('HYPEREXECUTE_JMX_PATH', 'hyperexecute-jmeter-/test.jmx')
    
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
    
    # Generate job label for display (will be used in trigger_job if not provided)
    if args.job_label is None:
        job_label_display = f"JMeter-{args.users}users-{args.duration}s-{args.rampup}s-rampup"
    else:
        job_label_display = args.job_label
    
    print("=" * 70)
    print("🚀 HyperExecute Automation Script")
    if args.debug:
        print("🐛 DEBUG MODE ENABLED")
    print("=" * 70)
    print(f"Configuration:")
    print(f"  - Username: {username}")
    print(f"  - Project ID: {project_id}")
    print(f"  - Users: {args.users}")
    print(f"  - Duration: {args.duration}s")
    print(f"  - Ramp-up: {args.rampup}s")
    print(f"  - Concurrency: {args.concurrency}")
    print(f"  - Job Label: {job_label_display}")
    print(f"  - JMX Path: {jmx_path}")
    if args.debug:
        print(f"  - Debug Mode: ON")
        print(f"  - Skip Download: {args.no_download}")
    print("=" * 70 + "\n")
    
    # Initialize API client
    api = HyperExecuteAPI(username, api_key, project_id)

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
        jmx_path=jmx_path
    )
    
    if not job_id:
        print("\n❌ Failed to trigger job. Exiting.")
        if args.debug:
            print("🐛 Debug Info: Check the response body above for API errors")
        sys.exit(1)
    
    # Step 2: Monitor job status
    job_completed = api.check_job_status(
        job_id=job_id,
        poll_interval=args.job_poll_interval
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
            artifact_name="JMeter",
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
