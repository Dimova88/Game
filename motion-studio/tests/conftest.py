import os
import sys
import tempfile
from pathlib import Path

# Los proyectos de prueba van a un directorio temporal (antes de importar la app).
os.environ.setdefault("MOTION_PROJECTS_DIR", tempfile.mkdtemp(prefix="motion-tests-"))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
