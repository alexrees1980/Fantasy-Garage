# The Car Vault v0.2.0

This release pivots the product from a standalone game into a personal vehicle
vault, while preserving Fantasy Garage as an optional add-on.

## Included

- Personal vault profile protected by username and PIN
- Permanent saved vehicle records independent of games
- Collections
- Tags, notes, status, mileage, source and price
- URL import with manual fallback
- Responsive three-column vault view
- Search and collection filters
- Archive function
- Fantasy Garage retained inside the same Streamlit app

## Deployment order

1. Open Supabase SQL Editor.
2. Run `car_vault_migration_v020.sql`.
3. Replace the current GitHub app files with this package.
4. Commit and allow Streamlit to redeploy.
5. Create your first vault profile and test manual/URL saving.
6. Keep using browser extension v0.1.6 for Fantasy Garage for now.

The next extension release will add a destination selector:

- My Car Vault
- Fantasy Garage
- Both

This is deliberately deferred until the vault tables and login flow have been
tested successfully.
