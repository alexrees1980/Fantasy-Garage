# Fantasy Garage

A configurable multiplayer fantasy vehicle garage game built with Streamlit and Supabase.

## Current features

- Create games with editable rules
- Six-character game codes
- Individual player PINs
- Multi-browser and multi-device play
- Persistent garages and valuations
- Private vehicle prices and notes
- Supabase image storage
- Reveal, valuation and results stages

## Streamlit secrets

Add these in Streamlit Community Cloud:

```toml
[supabase]
url = "https://YOUR-PROJECT.supabase.co"
service_key = "sb_secret_YOUR_SECRET_KEY"
```

Never commit the secret key to GitHub.

## URL-first advert importer

Players can paste an advert URL and the app will attempt to extract:

- Vehicle title
- Year
- Advertised price
- Location
- Advert type
- Description
- Lead image
- Source website

All imported fields are shown in an editable review form before saving.
Some websites may block or limit automated extraction, so manual completion
and image upload remain available.
