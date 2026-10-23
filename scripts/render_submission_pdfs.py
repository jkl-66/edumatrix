from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs" / "competition_submission_rebuild"
OUT = BASE / "pdf"
SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")


def render(doc: Path) -> str:
    profile = BASE / ("lo_profile_" + doc.stem)
    profile.mkdir(parents=True, exist_ok=True)
    profile_uri = "file:///" + urllib.parse.quote(str(profile).replace("\\", "/"), safe="/:")
    command = [
        str(SOFFICE),
        f"-env:UserInstallation={profile_uri}",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(OUT),
        str(doc),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=25)
        return f"{doc.name}: returncode={result.returncode} output={result.stdout[-160:].strip()}"
    except subprocess.TimeoutExpired:
        return f"{doc.name}: timeout (PDF may still have been written)"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    docs = sorted((BASE / "documents").glob("*.docx"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(render, docs):
            print(result)


if __name__ == "__main__":
    main()
