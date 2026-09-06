import subprocess
import sys


print("Installing Misa AI Core requirements...")
subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
print("Setup complete. Run: python -m misa_ai_core")
