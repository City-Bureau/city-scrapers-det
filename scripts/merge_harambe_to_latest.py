import json
import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings

    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    print("Warning: azure-storage-blob not installed")

DEFAULT_CONTAINER = "meetings-feed-det"
OUTPUT_BLOB = "latest.json"
UPCOMING_BLOB = "upcoming.json"
LOCAL_OUTPUT_DIR = "harambe_scrapers/output"
START_TIME_KEY = "start_time"

# Every scraper name the harambe pipeline can emit; old entries under these
# names are cleaned from latest.json on every merge. Also imported by
# archive_harambe.py so archiving covers the same set.
HARAMBE_SCRAPERS = [
    "det_dwcpa",
    "det_great_lakes_water_authority",
    "det_police_department",
    "det_police_fire_retirement",
    "mi_belle_isle",
    "wayne_health_human_services",
    "wayne_economic_development",
    "wayne_ethics_board",
    "wayne_government_operations",
    "wayne_ways_means",
    "wayne_audit",
    "wayne_public_services",
    "wayne_building_authority",
    "wayne_election_commission",
    "wayne_public_safety",
    "wayne_cow",
    "wayne_local_emergency_planning",
    "wayne_full_commission",
    # Derived names for county calendars without a registered agency
    # (see extractor/wayne_commission/common.py)
    "wayne_economic_development_events",
    "wayne_seniors_and_veterans_services_committee",
    "wayne_special_committees",
    "wayne_art_institute_authority",
    "wayne_board_of_canvassers",
    "wayne_brownfield_redevelopment_authority",
    "wayne_commission_youth_council",
    "wayne_wc_women_s_commission_meetings",
    "wayne_wc_zoological_authority_meetings",
    "wayne_parks_and_recreation_events",
    "wayne_environmental_services",
    "wayne_commission",
]

# Status-badge publishing. The harambe pipeline replaced the conventional Scrapy
# spiders for these scrapers but never re-implemented Scrapy's StatusExtension,
# so their city-scrapers-status/<name>.svg badges went stale. The Documenters
# report page and Airtable status sync read these badges, so we republish them
# here. Format mirrors city_scrapers_core.extensions.status: Documenters parses
# the FIRST <text> element as the status word.
STATUS_CONTAINER_ENV = "AZURE_STATUS_CONTAINER"
STATUS_BADGE_TZ = "America/Detroit"
STATUS_RUNNING = "running"
STATUS_FAILING = "failing"
STATUS_COLORS = {STATUS_RUNNING: "#44cc11", STATUS_FAILING: "#cb2431"}
# Status for a scraper that produced 0 meetings in an otherwise-successful run.
# The merge only runs after a successful scrape (the listing stage raises on a
# systemically empty calendar), so 0 meetings means the body is simply empty,
# not broken — mark it "running". Genuine breakage fails the job (badges are
# left untouched) and "gone dark" is owned by Documenters' days_broken health
# detection. Flip to STATUS_FAILING for city_scrapers_core's 0-items-is-failing
# rule (noisier: empty bodies then read failing).
EMPTY_RUN_STATUS = STATUS_RUNNING

STATUS_BADGE_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="144" height="20">
    <linearGradient id="b" x2="0" y2="100%">
        <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
        <stop offset="1" stop-opacity=".1"/>
    </linearGradient>
    <clipPath id="a">
        <rect width="144" height="20" rx="3" fill="#fff"/>
    </clipPath>
    <g clip-path="url(#a)">
        <path fill="#555" d="M0 0h67v20H0z"/>
        <path fill="{color}" d="M67 0h77v20H67z"/>
        <path fill="url(#b)" d="M0 0h144v20H0z"/>
    </g>
    <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="110">
        <text x="345" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)">{status}</text>
        <text x="345" y="140" transform="scale(.1)">{status}</text>
        <text x="1045" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)">{date}</text>
        <text x="1045" y="140" transform="scale(.1)">{date}</text>
    </g>
</svg>
"""  # noqa: E501


def get_azure_container_client(container_name: str = DEFAULT_CONTAINER):
    """Get Azure container client."""
    if not AZURE_AVAILABLE:
        raise ImportError("azure-storage-blob is required")

    account_name = os.getenv("AZURE_ACCOUNT_NAME")
    account_key = os.getenv("AZURE_ACCOUNT_KEY")

    if not account_name or not account_key:
        raise ValueError("AZURE_ACCOUNT_NAME and AZURE_ACCOUNT_KEY required")

    conn_str = (
        f"DefaultEndpointsProtocol=https;"
        f"AccountName={account_name};"
        f"AccountKey={account_key};"
        f"EndpointSuffix=core.windows.net"
    )

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    return blob_service.get_container_client(container_name)


def download_blob_from_azure(
    blob_name: str, container_name: str = DEFAULT_CONTAINER
) -> List[Dict]:
    """Download a JSON blob from Azure blob storage."""
    container_client = get_azure_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)

    print(f"Downloading {blob_name} from {container_name}...")

    try:
        content = blob_client.download_blob().readall().decode("utf-8")

        data = []
        for line in content.strip().split("\n"):
            if line:
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"  Skipping invalid JSON line: {e}")
                    continue

        print(f"  Downloaded {len(data)} meetings")
        return data
    except Exception as e:
        print(f"  Failed to download {blob_name}: {e}")
        return []


def read_harambe_from_local(output_dir: str = LOCAL_OUTPUT_DIR) -> List[Dict]:
    """Read latest Harambe scraper outputs from local files."""
    output_path = Path(output_dir)

    if not output_path.exists():
        print(f"  Local output directory not found: {output_dir}")
        return []

    print(f"\nReading latest Harambe outputs from {output_dir}/...")

    by_scraper = {}

    for json_file in output_path.glob("*.json"):
        filename = json_file.stem
        parts = filename.rsplit("_", 2)

        if len(parts) >= 3:
            scraper_name = parts[0]
            date_part = parts[1]
            time_part = parts[2]
            timestamp_str = f"{date_part}_{time_part}"

            if scraper_name not in by_scraper:
                by_scraper[scraper_name] = []

            by_scraper[scraper_name].append(
                {"file": json_file, "timestamp": timestamp_str, "name": scraper_name}
            )

    if not by_scraper:
        print(f"  No Harambe output files found in {output_dir}")
        return []

    all_meetings = []

    for scraper_name, files in by_scraper.items():
        latest = max(files, key=lambda x: x["timestamp"])

        print(f"  {scraper_name}: Using {latest['file'].name}")

        try:
            with open(latest["file"], "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        meeting = json.loads(line)
                        all_meetings.append(meeting)
        except Exception as e:
            print(f"    Error reading {latest['file'].name}: {e}")

    print(f"  Found {len(all_meetings)} Harambe meetings from local files")
    return all_meetings


def filter_out_scrapers(meetings: List[Dict], scraper_names: List[str]) -> List[Dict]:
    """Remove all meetings from specified scrapers."""
    filtered = []
    removed_count = 0

    for meeting in meetings:
        meeting_id = (
            meeting.get("extras", {}).get("cityscrapers/id")
            or meeting.get("extras", {}).get("cityscrapers.org/id")
            or ""
        )
        is_harambe = any(scraper_name in meeting_id for scraper_name in scraper_names)

        if not is_harambe:
            filtered.append(meeting)
        else:
            removed_count += 1

    if removed_count > 0:
        print(f"  Removed {removed_count} old Harambe meetings")

    return filtered


def upload_to_azure(
    data: List[Dict],
    blob_name: str = OUTPUT_BLOB,
    container_name: str = DEFAULT_CONTAINER,
) -> None:
    """Upload merged data to Azure blob storage."""
    container_client = get_azure_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)

    jsonlines_content = "\n".join(
        json.dumps(meeting, ensure_ascii=False) for meeting in data
    )
    blob_client.upload_blob(jsonlines_content, overwrite=True)

    print(f"  Uploaded to {blob_name} ({len(data)} meetings)")


def upload_scraper_files_to_azure(
    output_dir: str = LOCAL_OUTPUT_DIR,
    container_name: str = DEFAULT_CONTAINER,
) -> None:
    """Upload individual Harambe scraper output files to Azure root level."""
    output_path = Path(output_dir)

    if not output_path.exists():
        print(f"  Local output directory not found: {output_dir}")
        return

    container_client = get_azure_container_client(container_name)

    by_scraper = {}
    for json_file in output_path.glob("*.json"):
        filename = json_file.stem
        parts = filename.rsplit("_", 2)

        if len(parts) >= 3:
            scraper_name = parts[0]
            timestamp_str = f"{parts[1]}_{parts[2]}"

            if scraper_name not in by_scraper:
                by_scraper[scraper_name] = []

            by_scraper[scraper_name].append(
                {"file": json_file, "timestamp": timestamp_str}
            )

    for scraper_name, files in by_scraper.items():
        latest = max(files, key=lambda x: x["timestamp"])

        try:
            with open(latest["file"], "r") as f:
                content = f.read()

            blob_name = f"{scraper_name}.json"
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(content, overwrite=True)
            print(f"  Uploaded {blob_name}")
        except Exception as e:
            print(f"  Failed to upload {scraper_name}.json: {e}")


def filter_upcoming_meetings(meetings: List[Dict]) -> List[Dict]:
    """Filter meetings to only include future meetings (start_time > yesterday)."""
    yesterday_iso = (datetime.now() - timedelta(days=1)).isoformat()[:19]

    upcoming = [
        meeting for meeting in meetings if meeting[START_TIME_KEY][:19] > yesterday_iso
    ]

    return upcoming


def scraper_name_from_meeting(meeting: Dict) -> str:
    """Return the per-body scraper name encoded as the prefix of a meeting's
    cityscrapers/id (see harambe_scrapers/utils.generate_id: "<name>/<ts>/...")."""
    scraper_id = (
        meeting.get("extras", {}).get("cityscrapers/id")
        or meeting.get("extras", {}).get("cityscrapers.org/id")
        or ""
    )
    return scraper_id.split("/", 1)[0]


def build_status_svg(status: str, date_str: str) -> str:
    return STATUS_BADGE_SVG.format(
        color=STATUS_COLORS[status], status=status, date=date_str
    )


def write_status_badges(
    meetings: List[Dict],
    scraper_names: List[str],
    container_name: str = "",
) -> None:
    """Publish a per-scraper SVG status badge to the status container.

    Reaching the merge step means the scrape succeeded (the listing stage raises
    on a systemically empty calendar), so every scraper the pipeline owns is
    marked "running" — a 0-meeting body is empty, not broken (EMPTY_RUN_STATUS).
    Genuine breakage fails the job and leaves badges untouched; "gone dark" is
    owned by Documenters' days_broken health detection. Empty bodies are logged.
    """
    container_name = container_name or os.getenv(STATUS_CONTAINER_ENV)
    if not container_name:
        print(f"  {STATUS_CONTAINER_ENV} not set — skipping status badges")
        return

    try:
        counts = Counter(scraper_name_from_meeting(m) for m in meetings)
        date_str = datetime.now(ZoneInfo(STATUS_BADGE_TZ)).strftime("%Y-%m-%d")
        container_client = get_azure_container_client(container_name)
    except Exception as e:
        print(f"  Skipping status badges — could not init status container: {e}")
        return

    written = 0
    empty = []
    for name in scraper_names:
        has = counts.get(name, 0)
        status = STATUS_RUNNING if has else EMPTY_RUN_STATUS
        if not has:
            empty.append(name)
        try:
            container_client.get_blob_client(f"{name}.svg").upload_blob(
                build_status_svg(status, date_str),
                overwrite=True,
                content_settings=ContentSettings(
                    content_type="image/svg+xml", cache_control="no-cache"
                ),
            )
            written += 1
        except Exception as e:
            print(f"  Failed to write status badge for {name}: {e}")

    if empty:
        print(f"  No meetings this run (marked {EMPTY_RUN_STATUS}): {', '.join(empty)}")
    print(f"  Wrote {written}/{len(scraper_names)} status badges ({date_str})")


def main():
    print("=" * 70)
    print("Merging Harambe Scraper Outputs with Production Data")
    print("=" * 70)
    print()

    container_name = os.getenv("AZURE_CONTAINER", DEFAULT_CONTAINER)

    print("Configuration:")
    print(f"  Container: {container_name}")
    print("  Will update: latest.json, upcoming.json, and per-scraper files")
    print()

    harambe_scrapers = HARAMBE_SCRAPERS

    print(f"Harambe scrapers to process: {len(harambe_scrapers)} scrapers")
    print()

    existing_latest = download_blob_from_azure(OUTPUT_BLOB, container_name)
    existing_upcoming = download_blob_from_azure(UPCOMING_BLOB, container_name)

    harambe_meetings = read_harambe_from_local(LOCAL_OUTPUT_DIR)

    if not harambe_meetings:
        print("\nERROR: No Harambe output files found in local directory")
        print(f"  Expected location: {LOCAL_OUTPUT_DIR}")
        print("  Make sure Harambe scrapers have run before this merge step")
        exit(1)

    print("\nCleaning old Harambe data from latest.json...")
    cleaned_latest = filter_out_scrapers(existing_latest, harambe_scrapers)

    print("Cleaning old Harambe data from upcoming.json...")
    cleaned_upcoming = filter_out_scrapers(existing_upcoming, harambe_scrapers)

    harambe_upcoming = filter_upcoming_meetings(harambe_meetings)

    print("\nMerging data...")
    merged_latest = cleaned_latest + harambe_meetings
    merged_upcoming = cleaned_upcoming + harambe_upcoming

    print(
        f"  latest.json: {len(cleaned_latest)} conventional + "
        f"{len(harambe_meetings)} harambe = {len(merged_latest)} total"
    )
    print(
        f"  upcoming.json: {len(cleaned_upcoming)} conventional + "
        f"{len(harambe_upcoming)} harambe = {len(merged_upcoming)} total"
    )

    print("\nUploading merged data...")
    upload_to_azure(merged_latest, OUTPUT_BLOB, container_name)
    upload_to_azure(merged_upcoming, UPCOMING_BLOB, container_name)

    print("\nUploading individual scraper files...")
    upload_scraper_files_to_azure(LOCAL_OUTPUT_DIR, container_name)

    print("\nWriting scraper status badges...")
    write_status_badges(harambe_meetings, harambe_scrapers)

    print()
    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
