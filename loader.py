from pathlib import Path
import hashlib

from charset_normalizer import from_bytes

folder = Path(__file__).parent
documents = []
    
for file in folder.iterdir():
    if file.suffix == ".md":
        raw = file.read_bytes()
        result = from_bytes(raw).best()
        text = result.output()
        file_hash = hashlib.sha256(raw).hexdigest()
        documents.append({
            "filename": file.name,
            "text": text,
            "hash": file_hash
        })
