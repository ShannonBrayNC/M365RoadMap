# 0a) Is something shadowing the stdlib 'importlib'?
import importlib
import os
import sys

print("importlib module path:", getattr(importlib, "__file__", "<builtin>"))
print("sys.path[0]:", sys.path[0])

# 0b) If you see a path inside your repo (e.g. .\importlib.py or .\importlib\__init__.py), rename it:
import glob

# Find all importlib.py files recursively
for file in glob.glob("**/importlib.py", recursive=True):
    print("Found file:", file)

# Find all importlib directories recursively
for dirpath, dirnames, filenames in os.walk("."):
    if "importlib" in dirnames:
        print("Found directory:", os.path.join(dirpath, "importlib"))

# 0c) Remove/disable the *legacy* pre-commit hook so the new pre-commit manager runs cleanly:
legacy_hook = os.path.join(".git", "hooks", "pre-commit.legacy")
if os.path.exists(legacy_hook):
    os.remove(legacy_hook)
