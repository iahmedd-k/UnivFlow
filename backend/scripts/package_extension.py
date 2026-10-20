import os
import zipfile
from pathlib import Path

def package():
    # Target root: d:\Ahmed Dev\Projects\Uniflow
    root = Path(__file__).resolve().parents[2]
    ext_dir = root / "extension"
    out_zip = root / "uniflow-companion-store.zip"

    print(f"Packaging {ext_dir} into {out_zip}...")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in ext_dir.rglob("*"):
            if file.is_file() and not file.name.endswith(".DS_Store"):
                rel_path = file.relative_to(ext_dir)
                zipf.write(file, rel_path)
                print(f"  + {rel_path}")

    print(f"Success! Upload '{out_zip.name}' to the Chrome Web Store Developer Dashboard.")

if __name__ == "__main__":
    package()
