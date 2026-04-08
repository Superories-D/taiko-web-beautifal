import sys
import os

print("=== Diagnostic Start ===")
print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")
print(f"Platform: {sys.platform}")
print(f"CWD: {os.getcwd()}")

try:
    import PySide6
    print(f"PySide6 Version: {PySide6.__version__}")
    print(f"PySide6 Location: {os.path.dirname(PySide6.__file__)}")
except ImportError as e:
    print(f"CRITICAL: PySide6 package import failed: {e}")

print("-" * 20)

try:
    from PySide6 import QtCore
    print("SUCCESS: QtCore imported")
except ImportError as e:
    print(f"FAILURE: QtCore import failed: {e}")
    print("       Hint: This usually means missing VC++ Redistributable 2015-2022.")
    print("       Install mainly: https://aka.ms/vs/17/release/vc_redist.x64.exe")

print("-" * 20)

try:
    from PySide6 import QtWidgets
    print("SUCCESS: QtWidgets imported")
except ImportError as e:
    print(f"FAILURE: QtWidgets import failed: {e}")

print("=== Diagnostic End ===")
