import os
import subprocess

# The command to run the specific test case
command = "python -m pytest test_case/UI/Test_Katana/test_ui.py::test_case[smokecases15-chromium] -v"

# Execute the command in the autotest-monster directory
project_dir = os.path.dirname(os.path.abspath(__file__))
# Navigate up to the autotest-monster directory
project_dir = os.path.dirname(project_dir) 

# Run the command
try:
    subprocess.run(command, shell=True, check=True, cwd=project_dir)
except subprocess.CalledProcessError as e:
    print(f"An error occurred while running the test: {e}")