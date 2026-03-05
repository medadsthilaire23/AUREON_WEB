from pypdf import PdfReader, PdfWriter
import io


class PDFMergerService:
    def merge_pages(self, page_buffers: list) -> bytes:
        writer = PdfWriter()
        for buffer in page_buffers:
            if isinstance(buffer, bytes):
                buffer = io.BytesIO(buffer)
            buffer.seek(0)
            reader = PdfReader(buffer)
            for page in reader.pages:
                writer.add_page(page)
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        return output.getvalue()
