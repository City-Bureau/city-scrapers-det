"""
Unit tests for scripts/merge_harambe_to_latest.py
"""

import json
import os
import re
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from scripts.merge_harambe_to_latest import (
    STATUS_FAILING,
    STATUS_RUNNING,
    build_status_svg,
    download_blob_from_azure,
    filter_out_scrapers,
    filter_upcoming_meetings,
    read_harambe_from_local,
    scraper_name_from_meeting,
    upload_to_azure,
    write_status_badges,
)


@patch("scripts.merge_harambe_to_latest.BlobServiceClient")
def test_download_blob_from_azure(mock_blob_service):
    """Test downloading and parsing JSONLINES from Azure, skipping invalid lines."""
    mock_blob_client = Mock()
    mock_container_client = Mock()
    container = mock_blob_service.from_connection_string.return_value
    container.get_container_client.return_value = mock_container_client
    mock_container_client.get_blob_client.return_value = mock_blob_client

    jsonlines = '{"id": "m1"}\nINVALID\n{"id": "m2"}'
    mock_blob_client.download_blob.return_value.readall.return_value = (
        jsonlines.encode()
    )

    with patch.dict(
        os.environ, {"AZURE_ACCOUNT_NAME": "test", "AZURE_ACCOUNT_KEY": "test"}
    ):
        result = download_blob_from_azure("latest.json", "test-container")

    assert [m["id"] for m in result] == ["m1", "m2"]


def test_download_blob_missing_credentials():
    """Test that missing Azure credentials raises ValueError."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="AZURE_ACCOUNT_NAME"):
            download_blob_from_azure("latest.json", "test-container")


def test_read_harambe_from_local(tmp_path):
    """Test reading latest Harambe outputs, using newest file per scraper."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    (output_dir / "det_dwcpa_20251110_100000.json").write_text('{"id": "old"}\n')
    (output_dir / "det_dwcpa_20251113_120000.json").write_text('{"id": "new"}\n')

    result = read_harambe_from_local(str(output_dir))

    assert len(result) == 1
    assert result[0]["id"] == "new"

    # Missing directory returns empty
    assert read_harambe_from_local(str(tmp_path / "nonexistent")) == []


def test_filter_out_scrapers():
    """Test filtering meetings by scraper name using extras.cityscrapers/id."""
    meetings = [
        {"extras": {"cityscrapers/id": "det_council/20251113/meeting"}},
        {"extras": {"cityscrapers/id": "det_dwcpa/20251113/meeting"}},
        {"extras": {"cityscrapers/id": "det_glwa/20251113/meeting"}},
    ]

    result = filter_out_scrapers(meetings, ["det_dwcpa", "det_glwa"])

    assert len(result) == 1
    assert result[0]["extras"]["cityscrapers/id"] == "det_council/20251113/meeting"


def test_filter_upcoming_meetings():
    """Test filtering for future meetings, raising KeyError if start_time missing."""
    tomorrow = (datetime.now() + timedelta(days=1)).isoformat()[:19]
    yesterday = (datetime.now() - timedelta(days=2)).isoformat()[:19]

    meetings = [
        {"id": "future", "start_time": tomorrow},
        {"id": "past", "start_time": yesterday},
    ]

    result = filter_upcoming_meetings(meetings)

    assert len(result) == 1
    assert result[0]["id"] == "future"

    with pytest.raises(KeyError):
        filter_upcoming_meetings([{"id": "no_time"}])


@patch("scripts.merge_harambe_to_latest.BlobServiceClient")
def test_upload_to_azure(mock_blob_service):
    """Test uploading data to Azure in JSONLINES format."""
    mock_blob_client = Mock()
    mock_container_client = Mock()
    container = mock_blob_service.from_connection_string.return_value
    container.get_container_client.return_value = mock_container_client
    mock_container_client.get_blob_client.return_value = mock_blob_client

    with patch.dict(
        os.environ, {"AZURE_ACCOUNT_NAME": "test", "AZURE_ACCOUNT_KEY": "test"}
    ):
        upload_to_azure([{"id": "m1"}, {"id": "m2"}], "test.json", "test-container")

    uploaded = mock_blob_client.upload_blob.call_args[0][0]
    lines = uploaded.strip().split("\n")

    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "m1"


def _meeting(scraper_name):
    return {"extras": {"cityscrapers/id": f"{scraper_name}/202607161000/x/foo"}}


def test_scraper_name_from_meeting_uses_id_prefix():
    """Name is the id prefix — no substring collision between a base name and a
    longer derived one (wayne_economic_development vs ..._events)."""
    assert scraper_name_from_meeting(_meeting("wayne_audit")) == "wayne_audit"
    assert (
        scraper_name_from_meeting(_meeting("wayne_economic_development_events"))
        == "wayne_economic_development_events"
    )
    assert scraper_name_from_meeting({"extras": {}}) == ""


def test_build_status_svg_first_text_is_status_word():
    """Documenters parses the FIRST <text> element — it must be the status word."""
    svg = build_status_svg(STATUS_RUNNING, "2026-07-17")
    first_text = re.search(r"<text[^>]*>([^<]+)</text>", svg).group(1)
    assert first_text == "running"
    assert "#44cc11" in svg and "2026-07-17" in svg
    assert "#cb2431" in build_status_svg(STATUS_FAILING, "2026-07-17")


@patch("scripts.merge_harambe_to_latest.BlobServiceClient")
def test_write_status_badges_marks_all_running(mock_blob_service):
    """A successful merge marks every scraper running — a body with 0 meetings
    is empty, not broken (EMPTY_RUN_STATUS)."""
    mock_container = Mock()
    mock_blob_service.from_connection_string.return_value.get_container_client.return_value = (  # noqa: E501
        mock_container
    )
    blobs = {}
    mock_container.get_blob_client.side_effect = lambda n: blobs.setdefault(n, Mock())

    meetings = [_meeting("wayne_audit"), _meeting("wayne_audit")]
    names = ["wayne_audit", "wayne_local_emergency_planning"]

    with patch.dict(
        os.environ, {"AZURE_ACCOUNT_NAME": "test", "AZURE_ACCOUNT_KEY": "test"}
    ):
        write_status_badges(meetings, names, container_name="city-scrapers-status")

    audit_svg = blobs["wayne_audit.svg"].upload_blob.call_args[0][0]
    lepc_svg = blobs["wayne_local_emergency_planning.svg"].upload_blob.call_args[0][0]
    assert "running" in audit_svg and "#44cc11" in audit_svg
    # 0 meetings but still running (empty != failed)
    assert "running" in lepc_svg and "#44cc11" in lepc_svg


def test_write_status_badges_skipped_without_container():
    """No container arg and no env var -> no-op, no Azure access, no crash."""
    with patch.dict(os.environ, {}, clear=True):
        write_status_badges([_meeting("wayne_audit")], ["wayne_audit"])
