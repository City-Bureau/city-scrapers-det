#!/bin/bash
# Auto-discover and run all Harambe scrapers in parallel

# Find all Python files in harambe_scrapers/ (excluding __init__.py and observers.py)
for scraper in harambe_scrapers/*.py; do
    # Skip special files
    if [[ "$scraper" == *"__init__.py"* ]] || [[ "$scraper" == *"observers.py"* ]]; then
        continue
    fi

    echo "Starting: $scraper"
    pipenv run python "$scraper" &
done

# Wait for all background jobs to complete
wait

echo "All Harambe scrapers completed"
