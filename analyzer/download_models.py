"""Download the Essentia TensorFlow models at build time."""
import os
import urllib.request

from .meta import MOOD_HEADS

MODELS_DIR = os.environ.get("MODELS_DIR", "/app/models")
BASE = "https://essentia.upf.edu/models"

MODELS = {"msd-musicnn-1.pb": f"{BASE}/feature-extractors/musicnn/msd-musicnn-1.pb"}
for head in MOOD_HEADS:
    name = f"{head}-msd-musicnn-1.pb"
    MODELS[name] = f"{BASE}/classification-heads/{head}/{name}"

if __name__ == "__main__":
    os.makedirs(MODELS_DIR, exist_ok=True)
    for name, url in MODELS.items():
        path = os.path.join(MODELS_DIR, name)
        if os.path.exists(path):
            print(f"  skip {name}")
            continue
        print(f"  downloading {name}...")
        urllib.request.urlretrieve(url, path)
    print(f"All {len(MODELS)} models ready in {MODELS_DIR}")
