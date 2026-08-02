# Upgrade to v0.2.3

1. Open Supabase SQL Editor.
2. Run `car_vault_migration_v023.sql`.
3. Replace the current GitHub files with this package.
4. Commit and wait for Streamlit to redeploy.
5. Add a vault vehicle to the Fantasy Garage shortlist.
6. Move it from shortlist into the garage.
7. Confirm the image remains visible.

Existing garage vehicles may only regain their image automatically if a matching
shortlist record still exists. Newly transferred vehicles will always retain the
original advert image as a fallback.
