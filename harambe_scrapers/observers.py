"""
Simple data collection observers for Harambe scrapers.

Collects scraped data and optionally uploads to Azure Blob Storage
in a format compatible with Scrapy infrastructure.
"""

import json
import os
from datetime import datetime
from typing import Any

try:
    from azure.storage.blob import BlobServiceClient

    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False


class DataCollector:
    """
    Simple observer that collects data and optionally uploads to Azure.

    Usage:
        observer = DataCollector(
            scraper_name="det_police_fire",
            timezone="America/Detroit"
        )
        await SDK.run(
            scrape_func, url, observer=observer, harness=playwright_harness
        )
    """

    def __init__(self, scraper_name: str, timezone: str = "America/Detroit"):
        self.scraper_name = scraper_name
        self.timezone = timezone
        self.data = []
        self.azure_client = self._init_azure()

    def _init_azure(self):
        """Initialize Azure client if credentials available."""
        if not AZURE_AVAILABLE:
            return None

        account_name = os.getenv("AZURE_ACCOUNT_NAME")
        account_key = os.getenv("AZURE_ACCOUNT_KEY")
        container = os.getenv("AZURE_CONTAINER")

        if account_name and account_key and container:
            try:
                conn_str = (
                    f"DefaultEndpointsProtocol=https;"
                    f"AccountName={account_name};"
                    f"AccountKey={account_key};"
                    f"EndpointSuffix=core.windows.net"
                )
                return BlobServiceClient.from_connection_string(
                    conn_str
                ).get_container_client(container)
            except Exception as e:
                print(f"Azure init failed: {e}")
        return None

    async def on_save_data(self, data: dict[str, Any]):
        """Save data and upload to Azure if configured."""
        self.data.append(data)
        print(f"  ✓ {data.get('start_time', '')[:10]} - {data.get('name', 'Unknown')}")

        if self.azure_client:
            self._upload_to_azure(data)

    def _upload_to_azure(self, data: dict[str, Any]):
        """Upload to Azure in jsonlines format matching Scrapy pattern."""
        try:
            now = datetime.now()
            # Use .json extension to match Scrapy
            blob_path = (
                f"{now.year}/{now.month:02d}/{now.day:02d}/"
                f"{now.hour:02d}{now.minute:02d}/{self.scraper_name}.json"
            )
            blob_client = self.azure_client.get_blob_client(blob_path)

            # Append to blob (jsonlines format)
            json_line = json.dumps(data, ensure_ascii=False) + "\n"
            try:
                existing = blob_client.download_blob().readall().decode("utf-8")
                blob_client.upload_blob(existing + json_line, overwrite=True)
            except Exception:  # Blob doesn't exist yet
                blob_client.upload_blob(json_line)
        except Exception as e:
            print(f"  Azure upload failed: {e}")

    # Required observer interface
    async def on_queue_url(self, url, context, options):
        pass

    async def on_download(self, *args):
        return {}

    async def on_paginate(self, url):
        pass

    async def on_save_cookies(self, cookies):
        pass

    async def on_save_local_storage(self, storage):
        pass
