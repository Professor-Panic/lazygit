import os
import subprocess
import shlex
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
def GetBranchesList():
    output=getBranches()
    branches=[]
    for line in output.splitlines():
        if not line:
            continue
        branches.append(line)
    return branches
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
def getStashes():
    result = subprocess.run(
        ["git", "stash", "list"],
        capture_output=True,
        text=True
    )
    return result.stdout
def doCommand(command):
    try:
        args = shlex.split(command)
    except ValueError as e:
        return "", f"Could not parse command: {e}", 1

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", f"Command not found: {args[0]}", 127
    except PermissionError:
        return "", f"Permission denied: {args[0]}", 126
def stageFile(filename):
    result = subprocess.run(
        ["git", "add", filename],
        capture_output=True,
        text=True
    )
    return result.returncode == 0

def unstageFile(filename):
    result = subprocess.run(
        ["git", "restore", "--staged", filename],
        capture_output=True,
        text=True
    )
    return result.returncode == 0
def is_git_repo(path="."):
    return os.path.isdir(os.path.join(path, ".git"))
def doStash():
    result = subprocess.run(
        ["git", "stash"],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode

def switchBranch(branch):
    result = subprocess.run(
        ["git", "checkout", branch],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode

def doMerge(branch):
    result = subprocess.run(
        ["git", "merge", branch],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode

def doPull():
    result = subprocess.run(
        ["git", "pull"],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode

def doPush():
    result = subprocess.run(
        ["git", "push"],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode
def doStashFile(filename):
    result = subprocess.run(
        ["git", "stash","--",filename],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode
def getConflicts():
    """Returns a list of filenames that currently have unresolved merge conflicts."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        capture_output=True,
        text=True
    )
    return [line for line in result.stdout.splitlines() if line]

def isMergeInProgress(path="."):
    """True if a merge is currently in progress and awaiting resolution."""
    return os.path.isfile(os.path.join(path, ".git", "MERGE_HEAD"))

def abortMerge():
    result = subprocess.run(
        ["git", "merge", "--abort"],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode

def continueMerge():
    """Completes the merge after conflicts have been resolved and staged."""
    result = subprocess.run(
        ["git", "commit", "--no-edit"],
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode