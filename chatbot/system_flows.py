"""
Short workflow descriptions injected into chatbot context (system-only knowledge).

This is the authoritative, plain-language description of the CURRENT system flow.
Keep it accurate: the system has three roles (Administrator, QA Head, Faculty),
area-scoped faculty uploads, an Area Submissions monitor, and per-area ZIP
consolidation. There is no separate "Evidence Mapping" page or "Missing Document
Tracker" — documents are organized by accreditation Area instead.
"""


def system_workflows_text() -> str:
    return """
COMMON WORKFLOWS (QA Archiving System):

Roles & access:
- Administrator: full access — User Management, Settings, Audit Log, AI Processing, and Reports, plus everything the QA Head can do.
- QA Head (QA staff): the daily workflow across ALL accreditation areas — Dashboard, Upload, Repository, Smart Search, Area Submissions, Clusters, per-area consolidation, and deleting documents.
- Faculty: a contributor limited to their assigned accreditation area(s). Faculty can upload, view, search, edit, and download ONLY documents in their own area, and can edit or delete only their own uploads.

Upload: Sidebar -> Upload Document opens one page for a single file or many (drag-and-drop). Supported formats: PDF, DOCX, XLSX, JPG, PNG. Title, year and type are read from each file (correct them later with Edit). After upload the system extracts text (OCR for clear scans) and runs duplicate checks and clustering in the background. Faculty choose which of their assigned accreditation areas the files belong to.

Repository: Sidebar -> Document Repository lists every document. Filter by Program, Area, Year, File format, and Cluster, plus the Smart Search box. Columns: Title, Type, Year, Area, Cluster, Uploaded, and Uploaded by. Row actions: View (preview), Details, Edit, Download. The QA Head/Admin can choose an Area and click "Download area as ZIP" to consolidate every file in that area into one download. Faculty only ever see documents in their assigned area(s).

Area Submissions (QA Head/Admin only): Sidebar -> Area Submissions. Each accreditation area appears as a card showing assigned-faculty count, files submitted, submission progress (how many faculty have submitted), and the last upload date. Click an area to expand each assigned faculty member, see who has or has NOT submitted, and view the exact files each one uploaded. You can also download the whole area as a ZIP here. This is how the QA Head consolidates and monitors submissions per area.

Search: The Smart Search box (in the Repository) matches titles, extracted/OCR text, metadata, keywords, clusters, and accreditation area/program.

Dashboard: Total documents, duplicates to review, upload trend chart, monthly upload activity calendar, and file format breakdown. Filter by QA program and time period; Export Excel downloads a styled summary.

Reports (Admin): Document inventory, cluster distribution, and recent uploads, exportable as CSV/Excel.

Duplicates: AI flags possible duplicate uploads. See the count on the Dashboard or use the duplicates review filter in the Repository, then confirm or dismiss from a document's Details.

AI processing: After upload the system extracts text, applies OCR to clear scans, computes TF-IDF keywords, runs K-Means clustering within each accreditation area and document type (the silhouette score chooses each group's cluster count, with the Elbow Method as the fallback), and checks for duplicates. Admins can open AI Processing to see run status and the Elbow chart.

Notifications: The bell icon in the top bar shows recent alerts; Mark all read clears the badges without leaving your current page.

Users & Settings (Admin): User Management creates accounts and assigns each user a role and, for Faculty, their accreditation area(s). Settings holds system configuration; Audit Log records activity.
""".strip()


def general_system_guide() -> str:
    """Step-by-step overview for broad help questions — sidebar paths only, no URLs."""
    return (
        "Here is how this QA Archiving System works, step by step:\n\n"
        "1) Sign in by role\n"
        "   - Administrator: full access (users, settings, reports, AI processing).\n"
        "   - QA Head: the full document workflow across all accreditation areas.\n"
        "   - Faculty: upload and manage documents only within their assigned area(s).\n\n"
        "2) Upload documents\n"
        "   - Open Upload Document in the left sidebar; it takes one file or many at once.\n"
        "   - Optionally pick a QA program; title, year and type are read from each file.\n"
        "   - Faculty choose which of their assigned accreditation areas the files belong to.\n\n"
        "3) Find and manage files\n"
        "   - Open Document Repository to browse and filter by program, area, year, file format, or cluster.\n"
        "   - Use the Smart Search box when you know keywords but not the file name.\n"
        "   - Use View to preview, Details for metadata, Edit to change metadata, or Download.\n\n"
        "4) Consolidate per area (QA Head)\n"
        "   - In the Repository, pick an Area and click Download area as ZIP.\n"
        "   - Or open Area Submissions to see each area, which faculty have submitted, and download a whole area as a ZIP.\n\n"
        "5) Monitor progress\n"
        "   - Dashboard shows totals, duplicates to review, upload trend, calendar, and file formats.\n"
        "   - Click the bell in the top bar for alerts; use Mark all read when done.\n\n"
        "Ask about any one item for detail — e.g. \"How do I upload?\", "
        "\"How do I download an area as a ZIP?\", or \"What is Area Submissions?\""
    )


def build_full_system_context(request) -> str:
    return system_workflows_text()
