import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List


def parse_opml_file(path: Path) -> List[Dict[str, str]]:
    """Parse OPML file and extract feed information.

    Args:
        path: Path to OPML file

    Returns:
        List of feed dictionaries with 'name' and 'url' keys
    """
    path = resolve_opml_path(path)
    tree = ET.parse(path)
    root = tree.getroot()

    feeds = []
    for outline in root.findall(".//outline"):
        # Only process RSS/ATOM feed outlines
        if outline.get("type") in ("rss", "atom"):
            feeds.append(
                {
                    "name": outline.get("title", outline.get("text", "")),
                    "url": outline.get("xmlUrl", ""),
                }
            )

    return feeds


def resolve_opml_path(opml_path: Path) -> Path:
    """Resolve OPML file path to handle Docker environment."""
    if opml_path.exists():
        return opml_path

    potential_paths = [
        Path("/app/feeds") / opml_path.name,
        Path.cwd() / "feeds" / opml_path.name,
        Path("/app") / opml_path.name,
    ]

    for path in potential_paths:
        if path.exists():
            return path

    return opml_path
