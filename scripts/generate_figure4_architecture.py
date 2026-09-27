import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


def add_box(ax, x, y, w, h, text, fc="#f8fbff", ec="#2f5f98", fs=10, weight="normal"):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.008,rounding_size=0.015",
        linewidth=1.2,
        edgecolor=ec,
        facecolor=fc,
    )
    ax.add_patch(box)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fs,
        fontweight=weight,
        color="#1d2b3a",
        wrap=True,
    )


def add_arrow(ax, x1, y1, x2, y2):
    arr = FancyArrowPatch(
        (x1, y1),
        (x2, y2),
        arrowstyle="->",
        mutation_scale=12,
        linewidth=1.2,
        color="#2f5f98",
    )
    ax.add_patch(arr)


def main():
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
    ax = plt.axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(
        0.5,
        0.97,
        "Figure 4. System Architecture of the System",
        ha="center",
        va="center",
        fontsize=20,
        fontweight="bold",
        color="#1d2b3a",
    )

    # Layer headers
    layer_color = "#2f5f98"
    ax.text(0.02, 0.90, "Client Layer", fontsize=12, color=layer_color, fontweight="bold")
    ax.text(0.02, 0.76, "Application Layer (Django)", fontsize=12, color=layer_color, fontweight="bold")
    ax.text(0.02, 0.53, "Processing Layer", fontsize=12, color=layer_color, fontweight="bold")
    ax.text(0.02, 0.31, "Data Layer", fontsize=12, color=layer_color, fontweight="bold")
    ax.text(0.02, 0.18, "External Dependencies", fontsize=12, color=layer_color, fontweight="bold")

    # Client layer
    add_box(ax, 0.08, 0.84, 0.16, 0.06, "QA Head")
    add_box(ax, 0.27, 0.84, 0.16, 0.06, "Admin")
    add_box(ax, 0.46, 0.84, 0.20, 0.06, "Web Browser UI", fc="#eef6ff")

    # Application layer
    add_box(ax, 0.06, 0.68, 0.14, 0.07, "Authentication\n& Role Access")
    add_box(ax, 0.22, 0.68, 0.14, 0.07, "Document Upload")
    add_box(ax, 0.38, 0.68, 0.14, 0.07, "Metadata\nHandling")
    add_box(ax, 0.54, 0.68, 0.14, 0.07, "Repository")
    add_box(ax, 0.70, 0.68, 0.14, 0.07, "Smart Search")
    add_box(ax, 0.86, 0.68, 0.12, 0.07, "View /\nDownload")

    # Processing layer
    add_box(ax, 0.06, 0.45, 0.14, 0.07, "Text Extraction\n(PDF, DOCX, XLSX)")
    add_box(ax, 0.22, 0.45, 0.14, 0.07, "OCR Service\n(Images, Scanned PDF)")
    add_box(ax, 0.38, 0.45, 0.12, 0.07, "TF-IDF\nKeywords")
    add_box(ax, 0.52, 0.45, 0.10, 0.07, "Elbow\nMethod")
    add_box(ax, 0.64, 0.45, 0.10, 0.07, "K-Means\nClustering")
    add_box(ax, 0.76, 0.45, 0.12, 0.07, "Duplicate\nDetection")
    add_box(ax, 0.90, 0.45, 0.08, 0.07, "Hybrid\nRerank")
    add_box(ax, 0.38, 0.36, 0.24, 0.07, "Background Job Queue / Worker", fc="#eef6ff")

    # Data layer
    add_box(ax, 0.18, 0.24, 0.28, 0.07, "SQLite Database\n(Users, Metadata, AI Results, Logs, Jobs)", fc="#f2f8ff")
    add_box(ax, 0.52, 0.24, 0.28, 0.07, "File Storage (Media)\n(Uploaded Documents)", fc="#f2f8ff")

    # External dependencies
    add_box(ax, 0.20, 0.12, 0.18, 0.06, "Tesseract OCR", fc="#f6fbff")
    add_box(ax, 0.42, 0.12, 0.18, 0.06, "PyMuPDF / pdf2image", fc="#f6fbff")
    add_box(ax, 0.64, 0.12, 0.18, 0.06, "scikit-learn", fc="#f6fbff")

    # Outputs panel
    add_box(
        ax,
        0.82,
        0.24,
        0.16,
        0.18,
        "System Outputs\n\n• Searchable documents\n• Clustered groups\n• Duplicate alerts\n• Downloadable files",
        fc="#eef6ff",
        fs=9,
        weight="bold",
    )

    # Main flow arrows
    add_arrow(ax, 0.58, 0.84, 0.58, 0.75)
    add_arrow(ax, 0.29, 0.68, 0.29, 0.52)  # upload -> extraction
    add_arrow(ax, 0.45, 0.68, 0.44, 0.52)  # metadata -> tfidf
    add_arrow(ax, 0.77, 0.68, 0.94, 0.52)  # search -> rerank
    add_arrow(ax, 0.61, 0.68, 0.82, 0.68)  # repository -> search direction
    add_arrow(ax, 0.83, 0.68, 0.92, 0.68)  # search -> view/download
    add_arrow(ax, 0.44, 0.45, 0.44, 0.43)  # tfidf -> jobs
    add_arrow(ax, 0.57, 0.45, 0.57, 0.43)  # elbow/kmeans zone -> jobs
    add_arrow(ax, 0.50, 0.36, 0.32, 0.31)  # jobs -> db
    add_arrow(ax, 0.54, 0.68, 0.66, 0.31)  # repository -> file storage
    add_arrow(ax, 0.94, 0.42, 0.90, 0.33)  # rerank -> output
    add_arrow(ax, 0.82, 0.45, 0.85, 0.33)  # duplicate -> output
    add_arrow(ax, 0.66, 0.45, 0.84, 0.33)  # clustering -> output

    # Dependencies arrows
    add_arrow(ax, 0.29, 0.45, 0.29, 0.18)  # OCR -> Tesseract
    add_arrow(ax, 0.29, 0.45, 0.51, 0.18)  # OCR -> PyMuPDF/pdf2image
    add_arrow(ax, 0.44, 0.45, 0.73, 0.18)  # TF-IDF -> sklearn
    add_arrow(ax, 0.57, 0.45, 0.73, 0.18)  # Elbow -> sklearn
    add_arrow(ax, 0.69, 0.45, 0.73, 0.18)  # KMeans -> sklearn
    add_arrow(ax, 0.94, 0.45, 0.73, 0.18)  # Hybrid -> sklearn

    # Legend
    add_box(ax, 0.80, 0.08, 0.18, 0.06, "Legend:\nSolid arrows = data/process flow", fc="#ffffff", fs=9)

    output_path = "figure4_system_architecture.png"
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
