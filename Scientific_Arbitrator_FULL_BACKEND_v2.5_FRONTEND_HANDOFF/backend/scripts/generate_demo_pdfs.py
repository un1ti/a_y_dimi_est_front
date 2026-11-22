"""Create simple synthetic PDFs for API smoke tests. Not scientific publications."""
from pathlib import Path

import pymupdf


OUTPUT = Path(__file__).resolve().parents[1] / "demo_pdfs"
OUTPUT.mkdir(parents=True, exist_ok=True)
SAMPLES = {
    "demo_rag.pdf": "Synthetic example. Our RAG uses top_k=5, chunk_size=512 and Recall@5 = 0.82 on NQ.",
    "demo_solar.pdf": "Synthetic example. Perovskite cell: PCE = 21.4%, Voc = 1.08 V, Jsc = 22.5 mA/cm2, FF = 76%.",
}
for filename, content in SAMPLES.items():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((60, 75), content, fontsize=10)
        output = OUTPUT / filename
        pdf.save(output)
        print(output)
