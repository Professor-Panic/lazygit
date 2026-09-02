import os
import subprocess
def getFiles():
    result = subprocess.run(
    ["git", "status", "--porcelain"],
    capture_output=True,
    text=True)
    return result.stdout
def is_git_repo(path="."):
    return os.path.isdir(os.path.join(path, ".git"))