import os
import sys
PID_FILENAME = "python_pid.txt" # The name of the file to store the PID
try:
    # Get the current process's ID
    current_pid = os.getpid()
    # Write the PID to the specified file.
    # This file will be created in the current working directory of the Python script.
    # The shell script changes the CWD to the scenario-specific directory before running Python.
    with open(PID_FILENAME, "w") as pid_file:
        pid_file.write(str(current_pid))
    # Optional: Print a confirmation to standard output (will be logged by the shell script)
    # print(f"Successfully wrote PID {current_pid} to {PID_FILENAME}")
except Exception as e:
    # If any error occurs during PID file creation, print an error message to standard error.
    # This helps in debugging if the shell script cannot find the PID file.
    print(f"Critical Error: Could not write PID to {PID_FILENAME}. Error: {e}", file=sys.stderr)
    sys.exit(1) # Exit the script if PID cannot be written, as monitoring would fail.

from Metrics_Counter import monitor
import time

monitor.start(task_name = "sleep", sampling_interval = 0.1, output_format = "csv", additional_metrics=[], indices=[], position=(37,-122))

time.sleep(15)

monitor.stop()