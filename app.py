import hashlib
import hmac
import mimetypes
import secrets
from typing import Any, Dict, List, Optional

import streamlit as st
from supabase import Client, create_client

st.set_page_config(page_title="Fantasy Garage", page_icon="🏁", layout="wide")

BUCKET_NAME = "vehicle-images"


@st.cache_resource
def get_supabase() -> Client:
    try:
        return create_client(
            st.secrets["supabase"]["url"],
            st.secrets["supabase"]["service_key"],
        )
    except Exception:
        st.error(
            "Supabase secrets are missing. Add the project URL and service key "
            "in Streamlit Community Cloud under Settings → Secrets."
        )
        st.stop()


supabase = get_supabase()


def init_session() -> None:
    defaults = {
        "game_id": None,
        "player_id": None,
        "is_organiser": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode(),
        salt.encode(),
        120_000,
    ).hex()
    return f"{salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode(),
            salt.encode(),
            120_000,
        ).hex()
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def generate_game_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code.upper().strip() if ch.isalnum())


def money(game: Dict[str, Any], value: float) -> str:
    return f"{game.get('currency_symbol', '£')}{float(value):,.0f}"


def get_game(game_id: str) -> Optional[Dict[str, Any]]:
    result = supabase.table("games").select("*").eq("id", game_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_game_by_code(code: str) -> Optional[Dict[str, Any]]:
    result = (
        supabase.table("games")
        .select("*")
        .eq("game_code", normalise_code(code))
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_player(player_id: str) -> Optional[Dict[str, Any]]:
    result = supabase.table("players").select("*").eq("id", player_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_players(game_id: str) -> List[Dict[str, Any]]:
    return (
        supabase.table("players")
        .select("*")
        .eq("game_id", game_id)
        .order("created_at")
        .execute()
        .data
        or []
    )


def get_vehicles(game_id: str, player_id: Optional[str] = None) -> List[Dict[str, Any]]:
    query = (
        supabase.table("vehicles")
        .select("*")
        .eq("game_id", game_id)
        .order("created_at")
    )
    if player_id:
        query = query.eq("player_id", player_id)
    return query.execute().data or []


def get_valuations(game_id: str) -> List[Dict[str, Any]]:
    return (
        supabase.table("valuations")
        .select("*")
        .eq("game_id", game_id)
        .execute()
        .data
        or []
    )


def update_game(game_id: str, values: Dict[str, Any]) -> None:
    supabase.table("games").update(values).eq("id", game_id).execute()


def garage_stats(game: Dict[str, Any], player_id: str) -> Dict[str, Any]:
    vehicles = get_vehicles(game["id"], player_id)
    spent = sum(float(vehicle["purchase_price"]) for vehicle in vehicles)
    projects = sum(bool(vehicle.get("is_project")) for vehicle in vehicles)
    complete = (
        len(vehicles) == int(game["vehicle_count"])
        and spent <= float(game["total_budget"])
        and projects <= int(game["maximum_projects"])
    )
    return {
        "vehicles": vehicles,
        "spent": spent,
        "projects": projects,
        "complete": complete,
    }


def upload_image(game_code: str, player_id: str, upload) -> str:
    filename = "".join(
        ch if ch.isalnum() or ch in "._-" else "_"
        for ch in upload.name
    )[-120:]
    vehicle_token = secrets.token_hex(8)
    path = f"{game_code}/{player_id}/{vehicle_token}/{filename}"
    mime = upload.type or mimetypes.guess_type(filename)[0] or "image/jpeg"

    supabase.storage.from_(BUCKET_NAME).upload(
        path=path,
        file=upload.getvalue(),
        file_options={"content-type": mime, "upsert": "true"},
    )
    return path


def signed_image_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        result = supabase.storage.from_(BUCKET_NAME).create_signed_url(path, 3600)
        if isinstance(result, dict):
            return (
                result.get("signedURL")
                or result.get("signedUrl")
                or result.get("signed_url")
            )
    except Exception:
        return None
    return None


def logout() -> None:
    st.session_state.game_id = None
    st.session_state.player_id = None
    st.session_state.is_organiser = False
    st.rerun()


def rule_summary(game: Dict[str, Any]) -> None:
    with st.container(border=True):
        st.subheader(game["game_name"])
        cols = st.columns(4)
        cols[0].metric("Budget", money(game, game["total_budget"]))
        cols[1].metric("Vehicles", int(game["vehicle_count"]))
        cols[2].metric("Theme", game["vehicle_type"])
        cols[3].metric("Projects", int(game["maximum_projects"]))
        st.caption(
            f"Eligible years: {game['minimum_year']}–{game['maximum_year']} · "
            f"Vehicle price: {money(game, game['minimum_price'])}–"
            f"{money(game, game['maximum_price'])}"
        )
        if game.get("required_choices"):
            st.write(f"**Mandatory choices:** {game['required_choices']}")
        if game.get("custom_rules"):
            st.write(f"**Additional rules:** {game['custom_rules']}")


def create_game() -> None:
    st.header("Create a game")

    with st.form("create_game"):
        c1, c2 = st.columns(2)
        organiser_name = c1.text_input("Your name")
        organiser_pin = c2.text_input("Organiser PIN", type="password")

        game_name = st.text_input("Game name", value="£50k Garage Challenge")

        c1, c2, c3 = st.columns(3)
        currency = c1.selectbox("Currency", ["£", "€", "$"])
        budget = c2.number_input("Total budget", min_value=1_000, value=50_000, step=1_000)
        vehicle_count = c3.number_input("Vehicles per garage", min_value=1, max_value=20, value=5)

        c1, c2, c3 = st.columns(3)
        vehicle_type = c1.text_input("Vehicle theme", value="Classic cars")
        max_projects = c2.number_input("Maximum projects", min_value=0, max_value=20, value=1)
        location_rule = c3.text_input("Location restriction", value="Any location")

        c1, c2 = st.columns(2)
        min_price = c1.number_input("Minimum price per vehicle", min_value=0, value=0, step=500)
        max_price = c2.number_input("Maximum price per vehicle", min_value=0, value=50_000, step=500)

        c1, c2 = st.columns(2)
        min_year = c1.number_input("Earliest eligible year", min_value=1885, max_value=2100, value=1900)
        max_year = c2.number_input("Latest eligible year", min_value=1885, max_value=2100, value=1999)

        c1, c2 = st.columns(2)
        duplicates = c1.checkbox("Allow duplicate models")
        dealers = c1.checkbox("Allow dealer adverts", value=True)
        auctions = c2.checkbox("Allow auction adverts", value=True)

        required_choices = st.text_input(
            "Mandatory choices",
            placeholder="At least one British car and one convertible",
        )
        custom_rules = st.text_area(
            "Additional rules",
            value=(
                "Save an advert screenshot or link for validation. "
                "Purchase prices remain hidden during the reveal."
            ),
        )

        submitted = st.form_submit_button("Create game", type="primary")

    if not submitted:
        return

    errors = []
    if not organiser_name.strip():
        errors.append("Enter your name.")
    if len(organiser_pin) < 4:
        errors.append("Use a PIN of at least four characters.")
    if min_price > max_price:
        errors.append("Minimum price cannot exceed maximum price.")
    if min_year > max_year:
        errors.append("Earliest year cannot exceed latest year.")
    if max_projects > vehicle_count:
        errors.append("Project limit cannot exceed vehicle count.")

    if errors:
        for error in errors:
            st.error(error)
        return

    code = generate_game_code()
    while get_game_by_code(code):
        code = generate_game_code()

    game = (
        supabase.table("games")
        .insert(
            {
                "game_code": code,
                "game_name": game_name.strip() or "Fantasy Garage",
                "organiser_name": organiser_name.strip(),
                "organiser_pin_hash": hash_pin(organiser_pin),
                "currency_symbol": currency,
                "total_budget": float(budget),
                "vehicle_count": int(vehicle_count),
                "vehicle_type": vehicle_type.strip() or "Any vehicles",
                "minimum_price": float(min_price),
                "maximum_price": float(max_price),
                "minimum_year": int(min_year),
                "maximum_year": int(max_year),
                "maximum_projects": int(max_projects),
                "duplicates_allowed": duplicates,
                "dealer_adverts_allowed": dealers,
                "auction_adverts_allowed": auctions,
                "location_rule": location_rule.strip(),
                "required_choices": required_choices.strip(),
                "custom_rules": custom_rules.strip(),
                "stage": "setup",
            }
        )
        .execute()
        .data[0]
    )

    organiser = (
        supabase.table("players")
        .insert(
            {
                "game_id": game["id"],
                "player_name": organiser_name.strip(),
                "pin_hash": hash_pin(organiser_pin),
                "is_organiser": True,
                "garage_submitted": False,
            }
        )
        .execute()
        .data[0]
    )

    st.session_state.game_id = game["id"]
    st.session_state.player_id = organiser["id"]
    st.session_state.is_organiser = True
    st.rerun()


def join_game() -> None:
    st.header("Join a game")
    with st.form("join_game"):
        code = st.text_input("Game code")
        name = st.text_input("Player name")
        pin = st.text_input("Player PIN", type="password")
        submitted = st.form_submit_button("Join game", type="primary")

    if not submitted:
        return

    game = get_game_by_code(code)
    if not game:
        st.error("No game was found with that code.")
        return

    player = next(
        (
            p for p in get_players(game["id"])
            if p["player_name"].strip().casefold() == name.strip().casefold()
        ),
        None,
    )

    if not player or not verify_pin(pin, player["pin_hash"]):
        st.error("The player name or PIN is incorrect.")
        return

    st.session_state.game_id = game["id"]
    st.session_state.player_id = player["id"]
    st.session_state.is_organiser = bool(player["is_organiser"])
    st.rerun()


def landing_page() -> None:
    st.title("🏁 Fantasy Garage")
    st.caption("Create a challenge or join an existing game.")

    create_tab, join_tab = st.tabs(["Create a game", "Join a game"])
    with create_tab:
        create_game()
    with join_tab:
        join_game()


def organiser_setup(game: Dict[str, Any]) -> None:
    st.header("Organiser setup")
    st.success(f"Game code: **{game['game_code']}**")
    st.write("Add each player and give them a temporary PIN.")

    with st.form("add_player", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Player name")
        pin = c2.text_input("Temporary PIN", type="password")
        submitted = st.form_submit_button("Add player", type="primary")

    if submitted:
        if not name.strip():
            st.error("Enter a player name.")
        elif len(pin) < 4:
            st.error("Use a PIN of at least four characters.")
        else:
            try:
                supabase.table("players").insert(
                    {
                        "game_id": game["id"],
                        "player_name": name.strip(),
                        "pin_hash": hash_pin(pin),
                        "is_organiser": False,
                        "garage_submitted": False,
                    }
                ).execute()
                st.success(f"{name.strip()} added.")
                st.rerun()
            except Exception:
                st.error("That player name is already in this game.")

    players = get_players(game["id"])
    st.subheader("Players")
    for player in players:
        st.write(
            f"{'👑' if player['is_organiser'] else '👤'} "
            f"**{player['player_name']}**"
        )

    if len(players) >= 2:
        if st.button("Open garage building", type="primary"):
            update_game(game["id"], {"stage": "build"})
            st.rerun()
    else:
        st.info("Add at least one more player before starting.")


def validate_vehicle(
    game: Dict[str, Any],
    vehicles: List[Dict[str, Any]],
    vehicle: Dict[str, Any],
) -> List[str]:
    errors = []
    price = float(vehicle["purchase_price"])
    year = int(vehicle["vehicle_year"])

    if not vehicle["vehicle_name"].strip():
        errors.append("Enter the vehicle name.")
    if not int(game["minimum_year"]) <= year <= int(game["maximum_year"]):
        errors.append("The vehicle year is outside the permitted range.")
    if not float(game["minimum_price"]) <= price <= float(game["maximum_price"]):
        errors.append("The price is outside the permitted range.")
    if sum(float(v["purchase_price"]) for v in vehicles) + price > float(game["total_budget"]):
        errors.append("This would exceed the total budget.")
    if vehicle["is_project"]:
        project_count = sum(bool(v.get("is_project")) for v in vehicles)
        if project_count >= int(game["maximum_projects"]):
            errors.append("You have reached the project limit.")
    if vehicle["advert_type"] == "Dealer" and not game["dealer_adverts_allowed"]:
        errors.append("Dealer adverts are not allowed.")
    if vehicle["advert_type"] == "Auction" and not game["auction_adverts_allowed"]:
        errors.append("Auction listings are not allowed.")
    if not game["duplicates_allowed"]:
        names = {v["vehicle_name"].strip().casefold() for v in vehicles}
        if vehicle["vehicle_name"].strip().casefold() in names:
            errors.append("Duplicate selections are not allowed.")
    return errors


def show_vehicle(
    game: Dict[str, Any],
    vehicle: Dict[str, Any],
    private: bool,
    removable: bool = False,
) -> None:
    with st.container(border=True):
        c1, c2 = st.columns([1, 2])

        with c1:
            image_url = signed_image_url(vehicle.get("image_path"))
            if image_url:
                st.image(image_url, use_container_width=True)
            else:
                st.markdown("## 🚗")
                st.caption("No image uploaded")

        with c2:
            st.subheader(vehicle["vehicle_name"])
            details = [
                str(vehicle["vehicle_year"]),
                vehicle.get("advert_type", ""),
                vehicle.get("vehicle_location", ""),
            ]
            st.caption(" · ".join(filter(None, details)))

            if vehicle.get("is_project"):
                st.warning("Restoration project")

            if private:
                st.metric("Purchase price", money(game, vehicle["purchase_price"]))
                if vehicle.get("advert_url"):
                    st.link_button("Open advert", vehicle["advert_url"])
                if vehicle.get("private_notes"):
                    st.write(vehicle["private_notes"])
            else:
                st.info("Purchase price and private notes are hidden.")

            if removable and st.button(
                "Remove vehicle",
                key=f"remove_{vehicle['id']}",
            ):
                if vehicle.get("image_path"):
                    try:
                        supabase.storage.from_(BUCKET_NAME).remove(
                            [vehicle["image_path"]]
                        )
                    except Exception:
                        pass
                supabase.table("vehicles").delete().eq("id", vehicle["id"]).execute()
                st.rerun()


def build_garage(game: Dict[str, Any], player: Dict[str, Any]) -> None:
    stats = garage_stats(game, player["id"])
    vehicles = stats["vehicles"]

    rule_summary(game)
    st.header(f"{player['player_name']}'s garage")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vehicles", f"{len(vehicles)} / {game['vehicle_count']}")
    c2.metric("Spent", money(game, stats["spent"]))
    c3.metric(
        "Remaining",
        money(game, float(game["total_budget"]) - stats["spent"]),
    )
    c4.metric("Projects", f"{stats['projects']} / {game['maximum_projects']}")

    if player["garage_submitted"]:
        st.success("Your garage is submitted and locked.")
    elif len(vehicles) < int(game["vehicle_count"]):
        with st.form("add_vehicle", clear_on_submit=True):
            st.subheader(f"Add vehicle {len(vehicles) + 1}")
            c1, c2 = st.columns(2)
            name = c1.text_input("Year, make and model")
            year = c1.number_input(
                "Year",
                min_value=1885,
                max_value=2100,
                value=max(
                    int(game["minimum_year"]),
                    min(int(game["maximum_year"]), 1980),
                ),
            )
            price = c2.number_input(
                "Advertised price",
                min_value=0,
                max_value=int(game["total_budget"]),
                step=500,
            )
            advert_type = c2.selectbox(
                "Advert type",
                ["Private", "Dealer", "Auction", "Other"],
            )
            advert_url = st.text_input("Advert URL")
            location = st.text_input("Vehicle location")
            image = st.file_uploader(
                "Main image or advert screenshot",
                type=["jpg", "jpeg", "png", "webp"],
            )
            is_project = st.checkbox("Restoration project")
            notes = st.text_area("Private notes")
            submitted = st.form_submit_button("Add to garage", type="primary")

        if submitted:
            vehicle_data = {
                "game_id": game["id"],
                "player_id": player["id"],
                "vehicle_name": name.strip(),
                "vehicle_year": int(year),
                "purchase_price": float(price),
                "advert_type": advert_type,
                "advert_url": advert_url.strip(),
                "vehicle_location": location.strip(),
                "is_project": bool(is_project),
                "private_notes": notes.strip(),
                "image_path": None,
            }

            errors = validate_vehicle(game, vehicles, vehicle_data)
            if errors:
                for error in errors:
                    st.error(error)
            else:
                if image:
                    vehicle_data["image_path"] = upload_image(
                        game["game_code"],
                        player["id"],
                        image,
                    )
                supabase.table("vehicles").insert(vehicle_data).execute()
                st.success("Vehicle added.")
                st.rerun()

    st.divider()
    for vehicle in vehicles:
        show_vehicle(
            game,
            vehicle,
            private=True,
            removable=not player["garage_submitted"],
        )

    if (
        not player["garage_submitted"]
        and stats["complete"]
        and st.button("Submit and lock garage", type="primary")
    ):
        supabase.table("players").update(
            {"garage_submitted": True}
        ).eq("id", player["id"]).execute()
        st.rerun()


def reveal_page(game: Dict[str, Any]) -> None:
    rule_summary(game)
    st.header("Garage reveal")

    players = get_players(game["id"])
    selected_name = st.selectbox(
        "Choose a garage",
        [player["player_name"] for player in players],
    )
    selected = next(player for player in players if player["player_name"] == selected_name)

    for vehicle in get_vehicles(game["id"], selected["id"]):
        show_vehicle(game, vehicle, private=False)


def valuation_page(game: Dict[str, Any], player: Dict[str, Any]) -> None:
    st.header("Valuation round")
    st.caption("Value every vehicle except your own.")

    players = get_players(game["id"])
    existing = {
        item["vehicle_id"]: item
        for item in get_valuations(game["id"])
        if item["valuing_player_id"] == player["id"]
    }

    for owner in players:
        if owner["id"] == player["id"]:
            continue

        st.subheader(f"{owner['player_name']}'s garage")
        for vehicle in get_vehicles(game["id"], owner["id"]):
            show_vehicle(game, vehicle, private=False)
            current = existing.get(vehicle["id"], {}).get("valuation_amount", 0)

            value = st.number_input(
                f"Your valuation for {vehicle['vehicle_name']}",
                min_value=0,
                step=500,
                value=int(current),
                key=f"value_{vehicle['id']}",
            )

            if st.button("Save valuation", key=f"save_{vehicle['id']}"):
                payload = {
                    "game_id": game["id"],
                    "vehicle_id": vehicle["id"],
                    "valuing_player_id": player["id"],
                    "valuation_amount": float(value),
                }
                supabase.table("valuations").upsert(
                    payload,
                    on_conflict="vehicle_id,valuing_player_id",
                ).execute()
                st.success("Valuation saved.")
                st.rerun()


def results_page(game: Dict[str, Any]) -> None:
    st.header("Results")
    players = get_players(game["id"])
    vehicles = get_vehicles(game["id"])
    valuations = get_valuations(game["id"])

    rows = []
    for player in players:
        owned = [v for v in vehicles if v["player_id"] == player["id"]]
        cost = sum(float(v["purchase_price"]) for v in owned)

        vehicle_values = []
        for vehicle in owned:
            values = [
                float(v["valuation_amount"])
                for v in valuations
                if v["vehicle_id"] == vehicle["id"]
            ]
            vehicle_values.append(sum(values) / len(values) if values else 0)

        group_value = sum(vehicle_values)
        rows.append(
            {
                "player": player["player_name"],
                "cost": cost,
                "value": group_value,
                "profit": group_value - cost,
            }
        )

    rows.sort(key=lambda row: row["profit"], reverse=True)

    if rows:
        st.success(
            f"🏆 {rows[0]['player']} wins with "
            f"{money(game, rows[0]['profit'])} virtual profit."
        )

    for position, row in enumerate(rows, start=1):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Position", position)
            c2.metric("Player", row["player"])
            c3.metric("Group value", money(game, row["value"]))
            c4.metric("Profit / loss", money(game, row["profit"]))


def organiser_dashboard(game: Dict[str, Any]) -> None:
    st.header("Organiser controls")
    st.success(f"Game code: **{game['game_code']}**")

    players = get_players(game["id"])
    for player in players:
        stats = garage_stats(game, player["id"])
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.write(f"**{player['player_name']}**")
            c2.metric("Vehicles", f"{len(stats['vehicles'])}/{game['vehicle_count']}")
            c3.metric("Spent", money(game, stats["spent"]))
            c4.write("✅ Submitted" if player["garage_submitted"] else "⏳ Building")

    st.subheader("Move the game forward")
    stage = game["stage"]

    if stage == "build":
        if players and all(player["garage_submitted"] for player in players):
            if st.button("Open reveal", type="primary"):
                update_game(game["id"], {"stage": "reveal"})
                st.rerun()
        else:
            st.info("Reveal becomes available when every player has submitted.")

    elif stage == "reveal":
        if st.button("Open valuation round", type="primary"):
            update_game(game["id"], {"stage": "valuation"})
            st.rerun()

    elif stage == "valuation":
        if st.button("Publish results", type="primary"):
            update_game(game["id"], {"stage": "results"})
            st.rerun()

    elif stage == "results":
        st.success("Results are published.")


def app_page() -> None:
    game = get_game(st.session_state.game_id)
    player = get_player(st.session_state.player_id)

    if not game or not player:
        logout()
        return

    with st.sidebar:
        st.title("Fantasy Garage")
        st.write(f"**Game:** {game['game_code']}")
        st.write(f"**Player:** {player['player_name']}")
        st.write(f"**Stage:** {game['stage'].title()}")
        if st.button("Log out"):
            logout()

    st.title("🏁 Fantasy Garage")

    if player["is_organiser"] and game["stage"] == "setup":
        organiser_setup(game)
        return

    if player["is_organiser"]:
        with st.expander("Organiser controls", expanded=True):
            organiser_dashboard(game)

    if game["stage"] == "setup":
        st.info("The organiser is still setting up the game.")
    elif game["stage"] == "build":
        build_garage(game, player)
    elif game["stage"] == "reveal":
        reveal_page(game)
    elif game["stage"] == "valuation":
        valuation_page(game, player)
    elif game["stage"] == "results":
        results_page(game)


init_session()

if st.session_state.game_id and st.session_state.player_id:
    app_page()
else:
    landing_page()
