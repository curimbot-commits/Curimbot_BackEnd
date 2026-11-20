import io
import fitz  # PyMuPDF
import docx
from fastapi import HTTPException

def extract_text(file: io.BytesIO, filename: str) -> str:
    """
    Extrae el texto de un archivo (PDF, DOCX, TXT) dado un flujo de bytes.

    """
    name = filename.lower()
    data = file.read()
    if name.endswith(".pdf"):
        text = ""
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()
        return text
    elif name.endswith(".docx"):
        mem = io.BytesIO(data)
        d = docx.Document(mem)
        return "\n".join(p.text for p in d.paragraphs)
    elif name.endswith(".txt"):
        try:
            return data.decode("utf-8", errors="ignore")
        except:
            return data.decode("latin-1", errors="ignore")
    else:
        raise HTTPException(status_code=400, detail="Formato no soportado")
