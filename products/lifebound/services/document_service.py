"""
document_service.py
Construye el documento PDF final a partir de buffers de páginas.
"""
from typing import List
from infrastructure.pdf.pdf_merger_service import PDFMergerService

class DocumentService:
    def __init__(self):
        self._merger = PDFMergerService()

    def build(self, page_buffers: List[bytes]) -> bytes:
        if not page_buffers:
            raise ValueError("No pages to merge")
        return self._merger.merge_pages(page_buffers)
