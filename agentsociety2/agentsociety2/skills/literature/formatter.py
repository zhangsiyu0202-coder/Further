"""Literature formatting utilities

Functions for formatting literature entries as markdown and managing filenames.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Any


def sanitize_filename(filename: str) -> str:
    """Clean filename by removing illegal characters

    Args:
        filename: Original filename

    Returns:
        Sanitized filename safe for filesystem
    """
    # Remove or replace illegal characters
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", filename)
    sanitized = re.sub(r"\s+", "_", sanitized)
    sanitized = re.sub(r"_{2,}", "_", sanitized)
    return sanitized[:100]  # Limit length


def format_article_as_markdown(article: Dict[str, Any], query: str) -> str:
    """Format a single literature article as markdown

    Args:
        article: Article data dictionary
        query: Search query used to find the article

    Returns:
        Markdown formatted string
    """
    lines = []
    lines.append(f"# {article.get('title', 'Untitled Article')}")
    lines.append("")
    lines.append(f"**Search Query:** {query}")
    lines.append("")
    lines.append(f"**Saved At:** {datetime.now().isoformat()}")
    lines.append("")

    if article.get("journal"):
        lines.append(f"**Journal:** {article['journal']}")
        lines.append("")
    if article.get("doi"):
        lines.append(f"**DOI:** {article['doi']}")
        lines.append("")
    if article.get("avg_similarity") is not None:
        lines.append(f"**Similarity Score:** {article['avg_similarity']:.3f}")
        lines.append("")

    if article.get("abstract"):
        lines.append("## Abstract")
        lines.append("")
        lines.append(article["abstract"])
        lines.append("")

    # Add other fields
    exclude_fields = {"title", "journal", "doi", "abstract", "avg_similarity"}
    first_extra = True
    for key, value in article.items():
        if key not in exclude_fields and value is not None:
            if first_extra:
                lines.append("**Other Fields:**")
                lines.append("")
                first_extra = False
            lines.append(f"- **{key}:** {value}")
    if not first_extra:
        lines.append("")

    return "\n".join(lines)
