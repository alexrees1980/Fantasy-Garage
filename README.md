# Fantasy Garage

A configurable multiplayer fantasy car garage game where players build a collection within a set budget and compete on group valuation.

## Current beta features

- Editable total budget and currency
- Editable number of vehicles
- Custom vehicle type or theme
- Minimum and maximum price per vehicle
- Eligible year range
- Project-car limit
- Dealer and auction listing rules
- Duplicate vehicle rule
- Location restrictions
- Mandatory choices and custom rules
- Multiple players
- Image uploads and advert links
- Private garage-building view
- Purchase-price hiding during reveal
- Group valuation
- Automatic leaderboard and virtual-profit calculation

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Deploy `app.py` from this GitHub repository using Streamlit Community Cloud.

## Important beta limitation

This first version stores data in Streamlit session state. It is suitable for testing the complete game on one device or browser session. Persistent multiplayer games will require a database and shared image storage, planned for the next development stage.
