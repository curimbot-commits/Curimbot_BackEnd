
import time
import sys

def trace_import(name):
    start = time.time()
    print(f"Importing {name}...", end="", flush=True)
    try:
        __import__(name)
        print(f" Done ({time.time() - start:.2f}s)")
    except Exception as e:
        print(f" Failed ({time.time() - start:.2f}s): {e}")

modules_to_test = [
    "fastapi",
    "app.db.database",
    "app.api.v1.api",
    "app.services.session_service",
    "app.services.rag_service",
    "app.core.scheduler"
]

print("--- Startup Diagnostic ---")
for mod in modules_to_test:
    trace_import(mod)

print("Importing main...")
start = time.time()
import main
print(f"main imported in {time.time() - start:.2f}s")
