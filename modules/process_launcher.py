import subprocess
import os
import sys
import threading
import time

# Windows-specific imports for Job objects
if os.name == 'nt':
    import win32job
    import win32api

class ProcessManager:
    def __init__(self, on_output_callback=None, on_exit_callback=None):
        self.process = None
        self.job = None
        self.read_thread = None
        self.stop_thread = False
        self.on_output = on_output_callback or (lambda x: print(x, end=""))
        self.on_exit = on_exit_callback or (lambda x: None)

    def launch(self, target_path):
        if self.process:
            self.terminate()

        if not target_path or not os.path.exists(target_path):
            raise FileNotFoundError(f"Invalid target program path: '{target_path}'")

        print(f"Launching: {target_path}")

        # On Windows, set flags to create a new process group and prepare a Job object.
        if os.name == 'nt':
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            # Create the Job object configured to kill all processes on job close.
            self.job = win32job.CreateJobObject(None, "")
            job_info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
            job_info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, job_info)
        else:
            creation_flags = 0

        # Build the command.
        if target_path.endswith(".py"):
            if getattr(sys, 'frozen', False):
                cmd = ["python", "-u", target_path]
            else:
                cmd = [sys.executable, "-u", target_path]
        else:
            cmd = [target_path]

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            bufsize=-1,
            universal_newlines=False,
            creationflags=creation_flags,
            cwd=os.path.dirname(target_path)
        )

        # On Windows, assign the process to the Job object.
        if os.name == 'nt' and self.job:
            win32job.AssignProcessToJobObject(self.job, self.process._handle)

        self.stop_thread = False
        self.read_thread = threading.Thread(target=self._read_process_output)
        self.read_thread.daemon = True
        self.read_thread.start()

    def terminate(self):
        if not self.process:
            return

        print("Terminating running process and its children via job object...")
        self.stop_thread = True

        try:
            # On Windows, close the Job object handle; this will kill all processes in the job.
            if os.name == 'nt' and self.job:
                win32api.CloseHandle(self.job)
                self.job = None

            # Wait for the process to exit gracefully.
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                print("Process did not terminate within timeout, killing forcefully...")
                self.process.kill()
                self.process.wait(timeout=3)
        except Exception as e:
            print(f"Error terminating process: {e}")

        # Close stdout to unblock the reading thread.
        try:
            if self.process.stdout:
                self.process.stdout.close()
        except Exception as e:
            print(f"Error closing process stdout: {e}")

        self.process = None
        print("Process terminated")

        if self.read_thread and self.read_thread.is_alive():
            print("Waiting for output reader thread to complete...")
            self.read_thread.join(timeout=3)
            self.read_thread = None

    def _read_process_output(self):
        if not self.process:
            return
        
        try:
            while self.process and not self.stop_thread:
                if self.process.poll() is not None:
                    break
                try:
                    output = self.process.stdout.read(1)
                    if output:
                        try:
                            text = output.decode('utf-8', errors='replace')
                            self.on_output(text)
                        except Exception as e:
                            print(f"Decoding error: {e}")
                    else:
                        time.sleep(0.01)
                except Exception as e:
                    print(f"Read error: {e}")
                    time.sleep(0.1)
        except Exception as e:
            print(f"Output reader exception: {e}")
        finally:
            exit_code = None
            if self.process:
                try:
                    exit_code = self.process.poll()
                    if exit_code is None:
                        exit_code = self.process.wait(timeout=1)
                except:
                    pass
            self.on_exit(exit_code)
