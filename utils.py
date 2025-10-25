from pathlib import Path
from typing import Union
import pdfplumber
import docx
import io

def extract_text_from_file(path: Union[str, Path]) -> str:
    """Extract text content from .txt, .md, .pdf, .docx files."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in (".txt", ".md"):
        return p.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".pdf":
        text_chunks = []
        try:
            with pdfplumber.open(p) as pdf:
                for page in pdf.pages:
                    page_txt = page.extract_text()
                    if page_txt:
                        text_chunks.append(page_txt)
        except Exception as e:
            # fallback: attempt to read with binary and naive decode
            try:
                raw = p.read_bytes()
                text_chunks.append(raw.decode("utf-8", errors="ignore"))
            except Exception:
                raise e
        return "\n".join(text_chunks)
    elif suffix == ".docx":
        doc = docx.Document(p)
        paragraphs = [para.text for para in doc.paragraphs if para.text]
        return "\n".join(paragraphs)
    else:
        raise ValueError(f"Unsupported file suffix: {suffix}")