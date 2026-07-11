import sys
import os

print("=== Diagnostic Start ===")
print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")
print(f"Platform: {sys.platform}")
print(f"CWD: {os.getcwd()}")

try:
    import PyQt5
    print(f"PyQt5 Location: {os.path.dirname(PyQt5.__file__)}")
except ImportError as e:
    print(f"CRITICAL: PyQt5 package import failed: {e}")

print("-" * 20)

try:
    from PyQt5 import QtCore
    print("SUCCESS: QtCore imported")
except ImportError as e:
    print(f"FAILURE: QtCore import failed: {e}")
    print("       Hint: This usually means missing VC++ Redistributable 2015-2022.")
    print("       Install mainly: https://aka.ms/vs/17/release/vc_redist.x64.exe")

print("-" * 20)

try:
    from PyQt5 import QtWidgets
    print("SUCCESS: QtWidgets imported")
except ImportError as e:
    print(f"FAILURE: QtWidgets import failed: {e}")

print("=== Diagnostic End ===")
