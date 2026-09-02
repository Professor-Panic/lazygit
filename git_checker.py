import os
import subprocess
def getFiles():
    result = subprocess.run(
    ["git", "status", "--porcelain"],
    capture_output=True,
    text=True)
    return result.stdout
def GetFilesList():
    output = getFiles()
    files = []
    for line in output.splitlines():
        if not line:
            continue
        staged_status = line[0]
        unstaged_status = line[1]
        filename = line[3:]
        files.append({
            "filename": filename,
            "staged": staged_status,
            "unstaged": unstaged_status,
        })
    return files
def getBranches():
    result= subprocess.run(
    ["git", "branch"],
    capture_output=True,
    text=True)
    return result.stdout
def getDiff(filename):
    result= subprocess.run(
    ["git", "diff",filename],
    capture_output=True,
    text=True)
    return result.stdout
def doCommit(message):
    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode
def getCommits():
    result= subprocess.run(
    ["git", "log","--oneline"],
    capture_output=True,
    text=True)
    return result.stdout
def doCommand(command):
    args = command.split()
    result = subprocess.run(
        args,
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode
def is_git_repo(path="."):
    return os.path.isdir(os.path.join(path, ".git"))