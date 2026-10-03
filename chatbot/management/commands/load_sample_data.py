"""
Management command to load sample QA requirements and chatbot FAQs.
Usage: python manage.py load_sample_data
"""
from django.core.management.base import BaseCommand
from chatbot.models import ChatbotFAQ


class Command(BaseCommand):
    help = 'Load sample QA requirements and chatbot FAQs'

    def handle(self, *args, **options):
        self._load_faqs()
        self.stdout.write(self.style.SUCCESS('Sample data loaded successfully.'))

    def _load_faqs(self):
        faqs = [
            {'question': 'How do I upload a document?', 'answer': 'Go to "Upload Document" in the sidebar. Fill in the metadata form (title, year, document type, QA area) and select your file. Accepted formats are PDF, DOCX, XLSX, JPG, and PNG. Click "Upload Document" to submit. The system will automatically extract text and run initial processing.', 'category': 'upload', 'keywords': ['upload', 'document', 'file', 'submit', 'add']},
            {'question': 'What file types can I upload?', 'answer': 'The system accepts PDF, DOCX, XLSX, JPG, and PNG files. Maximum file size is 25MB. For best results with text extraction, use machine-readable PDFs or DOCX files.', 'category': 'upload', 'keywords': ['file', 'type', 'format', 'accept', 'pdf', 'docx', 'xlsx']},
            {'question': 'How do I search for a document?', 'answer': 'Open "Repository" in the sidebar and use the Smart Search box at the top of the page. You can also filter by year, document type, QA area, and cluster. The search looks through document titles, descriptions, extracted text, and metadata.', 'category': 'search', 'keywords': ['search', 'find', 'query', 'look', 'filter']},
            {'question': 'What is OCR?', 'answer': 'OCR stands for Optical Character Recognition. It is a technology that converts images of text (such as scanned documents or photos) into machine-readable text. This allows the system to extract text from image-based files like JPG and PNG. Note: OCR is currently disabled in this version.', 'category': 'ai', 'keywords': ['ocr', 'optical', 'character', 'recognition', 'scan', 'image']},
            {'question': 'What is TF-IDF?', 'answer': 'TF-IDF stands for Term Frequency-Inverse Document Frequency. It is a statistical method used to identify the most important keywords in a document relative to the entire collection. Words that appear frequently in one document but rarely across all documents receive higher TF-IDF scores, indicating they are more significant for that document.', 'category': 'ai', 'keywords': ['tfidf', 'tf-idf', 'keyword', 'term', 'frequency', 'important']},
            {'question': 'What is K-Means clustering?', 'answer': 'K-Means is a machine learning algorithm that groups similar documents into clusters based on their content. Documents with similar keywords and topics are placed in the same cluster. This helps identify related documents and discover patterns in the document collection.', 'category': 'ai', 'keywords': ['kmeans', 'k-means', 'cluster', 'group', 'similar', 'algorithm']},
            {'question': 'What is the Elbow Method?', 'answer': 'The Elbow Method is a technique used to determine the optimal number of clusters for K-Means. It tests different numbers of clusters and plots the inertia (measure of how tight the clusters are). The "elbow" point in the graph indicates the best balance between number of clusters and cluster quality.', 'category': 'ai', 'keywords': ['elbow', 'method', 'optimal', 'cluster', 'number', 'inertia']},
            {'question': 'How do I run document analysis?', 'answer': 'Go to "Document Analysis" in the sidebar and click the "Run Document Analysis" button. This will analyze all uploaded documents by extracting keywords (TF-IDF), determining optimal clusters (Elbow Method), grouping documents (K-Means), checking for duplicates, and generating recommendations. Make sure you have at least 2 documents uploaded.', 'category': 'ai', 'keywords': ['run', 'process', 'ai', 'analyze', 'cluster', 'processing']},
            {'question': 'What are the user roles?', 'answer': 'There are three roles: Admin (full access including user management and settings), QA Head (office operations such as upload, repository, and search), and Faculty (upload and view documents for their assigned accreditation area only). Your role is shown under your username in the sidebar.', 'category': 'general', 'keywords': ['role', 'permission', 'admin', 'qa head', 'faculty', 'access']},
            {'question': 'How do I generate reports?', 'answer': 'Go to "Reports" in the sidebar. Select a report type: Document Inventory, Cluster Distribution, or Recent Uploads. You can export any report as CSV or print it directly from the page.', 'category': 'general', 'keywords': ['report', 'generate', 'export', 'csv', 'print', 'summary']},
        ]

        count = 0
        for f in faqs:
            _, created = ChatbotFAQ.objects.get_or_create(
                question=f['question'],
                defaults={'answer': f['answer'], 'category': f['category'], 'keywords': f['keywords']}
            )
            if created:
                count += 1
        self.stdout.write(f'  Created {count} chatbot FAQs.')
