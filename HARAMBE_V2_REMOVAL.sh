#!/bin/bash
# Script to remove _v2 postfix from Harambe scrapers in city-scrapers-det

echo "Removing _v2 postfix from Harambe scrapers in city-scrapers-det..."

# Update SCRAPER_NAME constants
sed -i '' 's/SCRAPER_NAME = "det_police_department_v2"/SCRAPER_NAME = "det_police_department"/' harambe_scrapers/det_police_department.py
sed -i '' 's/SCRAPER_NAME = "det_police_fire_retirement_v2"/SCRAPER_NAME = "det_police_fire_retirement"/' harambe_scrapers/det_police_fire_retirement.py
sed -i '' 's/SCRAPER_NAME = "det_dwcpa_v2"/SCRAPER_NAME = "det_dwcpa"/' harambe_scrapers/det_dwcpa.py
sed -i '' 's/SCRAPER_NAME = "mi_belle_isle_v2"/SCRAPER_NAME = "mi_belle_isle"/' harambe_scrapers/mi_belle_isle.py
sed -i '' 's/SCRAPER_NAME = "det_great_lakes_water_authority_v2"/SCRAPER_NAME = "det_great_lakes_water_authority"/' harambe_scrapers/det_great_lakes_water_authority.py

# Also update any references in output filenames
find harambe_scrapers -name "*.py" -type f -exec sed -i '' 's/_v2_/_/g' {} \;
find harambe_scrapers -name "*.py" -type f -exec sed -i '' 's/"_v2"/""/g' {} \;

echo "Done! Updated scrapers:"
echo "  - det_police_department"
echo "  - det_police_fire_retirement"
echo "  - det_dwcpa"
echo "  - mi_belle_isle"
echo "  - det_great_lakes_water_authority"