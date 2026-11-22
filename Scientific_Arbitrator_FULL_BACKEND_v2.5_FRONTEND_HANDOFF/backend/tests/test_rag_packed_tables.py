import unittest
from types import SimpleNamespace

import pymupdf

from app.services.pdf_parser import extract_table_fragments
from app.services.rag_table_extraction import extract_rag_table_records


class PackedTableTest(unittest.TestCase):
    def test_group_headers_keep_scores_with_their_method_and_subset(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            for y in (80, 120, 180):
                page.draw_line((40, y), (430, y))
            page.draw_line((130, 100), (430, 100))
            for x in (40, 130, 280, 430):
                page.draw_line((x, 80), (x, 180))
            for x, y, text in [
                (46, 102, "RAG Flow"), (155, 95, "QA#test"), (305, 95, "QA#all"),
                (142, 114, "BLEU"), (205, 114, "ROUGE-L"),
                (292, 114, "BLEU"), (355, 114, "ROUGE-L"),
                (46, 141, "First system"), (46, 162, "Second system"),
                (142, 141, "0.11"), (205, 141, "0.21"), (292, 141, "0.31"), (355, 141, "0.41"),
                (142, 162, "0.12"), (205, 162, "0.22"), (292, 162, "0.32"), (355, 162, "0.42"),
            ]:
                page.insert_text((x, y), text, fontsize=9)
            fragments = [SimpleNamespace(id=str(i), text=text, page=1)
                         for i, text in enumerate(extract_table_fragments(page))]
            records = extract_rag_table_records(fragments).records
            self.assertEqual(len(records), 8)
            values = {(r["rag_variant"], r["dataset_name"], r["metric_name"]): r["metric_value"]
                      for r in records}
            self.assertEqual(values["First system", "QA#test", "BLEU"], 0.11)
            self.assertEqual(values["Second system", "QA#all", "ROUGE-L"], 0.42)
