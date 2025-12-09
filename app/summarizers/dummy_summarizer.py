from .base_summarizer import BaseSummarizer

class DummySummarizer(BaseSummarizer):
    def extract_text(self, pdf_path):
        return f"[Extracted text from {pdf_path}]"

    def summarize_text(self, text, title):
        return f"(Simulated summary for {title})"
