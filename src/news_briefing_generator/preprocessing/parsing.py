from datetime import datetime

import pytz
from bs4 import BeautifulSoup


def html_to_text(html: str) -> str | None:
    """Convert HTML content to plain text."""
    # Check if the input is not None and is a string
    if html and isinstance(html, str):
        # Parse the HTML content
        soup = BeautifulSoup(html, "html.parser")
        # Extract and return the text content
        return soup.get_text()
    return html


def to_dt_utc(s: str) -> datetime | None:
    # There's an issue with parsing timestamps in format "%a, %d %b %Y %H:%M:%S %Z"
    # for the timezone value %Z, see: https://github.com/python/cpython/issues/66571

    if not s:
        return None

    date_formats = [
        "%a, %d %b %Y %H:%M:%S %Z",  # Mon, 18 Nov 2024 18:55:24 GMT
        "%a, %d %b %Y %H:%M:%S %z",  # Mon, 18 Nov 2024 21:05:34 +0000
        "%Y-%m-%dT%H:%M:%S%z",  # 2024-11-19T02:03:27+05:30
    ]
    tz_mapping = {"EDT": "US/Eastern"}

    for date_format in date_formats:
        try:
            dt = datetime.strptime(s, date_format)

            if not dt.tzinfo:
                # Assuming that this only happens for format '%a, %d %b %Y %H:%M:%S %Z'
                Z = s[-3:]
                tz = tz_mapping[Z] if Z in tz_mapping else Z
                timezone = pytz.timezone(tz)
                dt = timezone.localize(dt)

            dt_utc = dt.astimezone(pytz.UTC)
            return dt_utc
        except ValueError:
            continue

    return None
