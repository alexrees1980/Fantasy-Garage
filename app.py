import copy
import re
from typing import Dict, List

import streamlit as st

st.set_page_config(
    page_title="Fantasy Garage",
    page_icon="🏁",
    layout="wide",
)

DEFAULT_RULES = {
    "game_name": "£50k Garage Challenge",
    "currency_symbol": "£",
    "budget": 50_000,
    "vehicle_count": 5,
    "vehicle_type": "Classic cars",
    "minimum_price": 0,
    "maximum_price": 50_000,
    "minimum_year": 1900,
    "maximum_year": 1999,
    "maximum_projects": 1,
    "duplicates_allowed": False,
    "dealer_adverts_allowed": True,
    "auction_adverts_allowed": True,
    "location_rule": "Any location",
    "required_choices": "None",
    "custom_rules": (
        "Save a screenshot of every advert for validation. "
        "Only the vehicle image and description are shown during the reveal."
    ),
}


def init_state() -> None:
    defaults = {
        "rules": copy.deepcopy(DEFAULT_RULES),
        "players": ["Alex", "Richard", "Jamie", "Dan"],
        "garages": {},
        "valuations": {},
        "stage": "Setup",
        "active_builder": "Alex",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    for player in st.session_state.players:
        st.session_state.garages.setdefault(player, [])


def money(value: float) -> str:
    return f"{st.session_state.rules['currency_symbol']}{value:,.0f}"


def clean_players(raw: str) -> List[str]:
    result = []
    for line in raw.splitlines():
        name = line.strip()
        if name and name not in result:
            result.append(name)
    return result


def sync_players(players: List[str]) -> None:
    old = st.session_state.garages
    st.session_state.players = players
    st.session_state.garages = {player: old.get(player, []) for player in players}
    st.session_state.valuations = {
        key: value
        for key, value in st.session_state.valuations.items()
        if key.split("::", 1)[0] in players
    }
    if players and st.session_state.active_builder not in players:
        st.session_state.active_builder = players[0]


def total_spend(player: str) -> float:
    return sum(car["price"] for car in st.session_state.garages.get(player, []))


def project_count(player: str) -> int:
    return sum(bool(car.get("is_project")) for car in st.session_state.garages.get(player, []))


def garage_complete(player: str) -> bool:
    rules = st.session_state.rules
    garage = st.session_state.garages.get(player, [])
    return (
        len(garage) == rules["vehicle_count"]
        and total_spend(player) <= rules["budget"]
        and project_count(player) <= rules["maximum_projects"]
    )


def all_complete() -> bool:
    return bool(st.session_state.players) and all(
        garage_complete(player) for player in st.session_state.players
    )


def reset_game() -> None:
    st.session_state.garages = {player: [] for player in st.session_state.players}
    st.session_state.valuations = {}
    st.session_state.stage = "Setup"


def rule_summary() -> None:
    rules = st.session_state.rules
    with st.container(border=True):
        st.write(f"### {rules['game_name']}")
        cols = st.columns(4)
        cols[0].metric("Budget", money(rules["budget"]))
        cols[1].metric("Vehicles", rules["vehicle_count"])
        cols[2].metric("Type", rules["vehicle_type"])
        cols[3].metric("Projects allowed", rules["maximum_projects"])
        st.caption(
            f"Eligible years: {rules['minimum_year']}–{rules['maximum_year']} · "
            f"Price per vehicle: {money(rules['minimum_price'])}–{money(rules['maximum_price'])}"
        )


def setup_page() -> None:
    st.header("Game setup")
    st.caption("The organiser can tailor the challenge before anyone starts building.")

    rules = st.session_state.rules

    with st.form("rules_form"):
        st.subheader("Core parameters")
        c1, c2, c3 = st.columns(3)
        game_name = c1.text_input("Game name", value=rules["game_name"])
        currency_symbol = c2.selectbox(
            "Currency",
            ["£", "€", "$"],
            index=["£", "€", "$"].index(rules["currency_symbol"]),
        )
        vehicle_type = c3.text_input("Vehicle type or theme", value=rules["vehicle_type"])

        c1, c2, c3 = st.columns(3)
        budget = c1.number_input(
            "Total budget",
            min_value=1_000,
            max_value=100_000_000,
            value=int(rules["budget"]),
            step=1_000,
        )
        vehicle_count = c2.number_input(
            "Vehicles per garage",
            min_value=1,
            max_value=20,
            value=int(rules["vehicle_count"]),
            step=1,
        )
        maximum_projects = c3.number_input(
            "Maximum projects",
            min_value=0,
            max_value=20,
            value=int(rules["maximum_projects"]),
            step=1,
        )

        st.subheader("Eligibility and limitations")
        c1, c2 = st.columns(2)
        minimum_price = c1.number_input(
            "Minimum price per vehicle",
            min_value=0,
            max_value=int(budget),
            value=min(int(rules["minimum_price"]), int(budget)),
            step=500,
        )
        maximum_price = c2.number_input(
            "Maximum price per vehicle",
            min_value=0,
            max_value=int(budget),
            value=min(int(rules["maximum_price"]), int(budget)),
            step=500,
        )

        c1, c2 = st.columns(2)
        minimum_year = c1.number_input(
            "Earliest eligible year",
            min_value=1885,
            max_value=2100,
            value=int(rules["minimum_year"]),
            step=1,
        )
        maximum_year = c2.number_input(
            "Latest eligible year",
            min_value=1885,
            max_value=2100,
            value=int(rules["maximum_year"]),
            step=1,
        )

        c1, c2 = st.columns(2)
        duplicates_allowed = c1.checkbox(
            "Allow duplicate models in one garage",
            value=rules["duplicates_allowed"],
        )
        dealer_adverts_allowed = c1.checkbox(
            "Allow dealer adverts",
            value=rules["dealer_adverts_allowed"],
        )
        auction_adverts_allowed = c2.checkbox(
            "Allow auction listings",
            value=rules["auction_adverts_allowed"],
        )

        location_rule = c2.text_input(
            "Location restriction",
            value=rules["location_rule"],
        )
        required_choices = st.text_input(
            "Mandatory choices",
            value=rules["required_choices"],
            help="Example: at least one British car and one convertible.",
        )
        custom_rules = st.text_area(
            "Additional rules",
            value=rules["custom_rules"],
            height=120,
        )

        saved = st.form_submit_button("Save game parameters", type="primary")

        if saved:
            errors = []
            if minimum_price > maximum_price:
                errors.append("Minimum price cannot exceed maximum price.")
            if minimum_year > maximum_year:
                errors.append("Earliest year cannot be later than latest year.")
            if maximum_projects > vehicle_count:
                errors.append("Maximum projects cannot exceed the number of vehicles.")

            if errors:
                for error in errors:
                    st.error(error)
            else:
                st.session_state.rules = {
                    "game_name": game_name.strip() or "Fantasy Garage",
                    "currency_symbol": currency_symbol,
                    "budget": int(budget),
                    "vehicle_count": int(vehicle_count),
                    "vehicle_type": vehicle_type.strip() or "Any vehicles",
                    "minimum_price": int(minimum_price),
                    "maximum_price": int(maximum_price),
                    "minimum_year": int(minimum_year),
                    "maximum_year": int(maximum_year),
                    "maximum_projects": int(maximum_projects),
                    "duplicates_allowed": duplicates_allowed,
                    "dealer_adverts_allowed": dealer_adverts_allowed,
                    "auction_adverts_allowed": auction_adverts_allowed,
                    "location_rule": location_rule.strip() or "Any location",
                    "required_choices": required_choices.strip() or "None",
                    "custom_rules": custom_rules.strip(),
                }
                st.success("Game parameters saved.")

    st.divider()
    st.subheader("Players")
    player_text = st.text_area(
        "Enter one player per line",
        value="\n".join(st.session_state.players),
        height=150,
    )
    c1, c2 = st.columns(2)
    if c1.button("Save players", use_container_width=True):
        players = clean_players(player_text)
        if len(players) < 2:
            st.error("Add at least two players.")
        else:
            sync_players(players)
            st.success("Players saved.")
            st.rerun()

    if c2.button("Reset garages and scores", use_container_width=True):
        reset_game()
        st.success("The current game has been reset.")
        st.rerun()

    rule_summary()

    if st.session_state.players and st.button("Start building garages", type="primary"):
        st.session_state.stage = "Build"
        st.rerun()


def validate_car(player: str, car: Dict) -> List[str]:
    rules = st.session_state.rules
    garage = st.session_state.garages[player]
    errors = []

    if not car["name"].strip():
        errors.append("Enter the vehicle's year, make and model.")
    if car["price"] < rules["minimum_price"] or car["price"] > rules["maximum_price"]:
        errors.append(
            f"The price must be between {money(rules['minimum_price'])} "
            f"and {money(rules['maximum_price'])}."
        )
    if car["year"] < rules["minimum_year"] or car["year"] > rules["maximum_year"]:
        errors.append(
            f"The year must be between {rules['minimum_year']} and {rules['maximum_year']}."
        )
    if total_spend(player) + car["price"] > rules["budget"]:
        errors.append("This purchase would exceed the total garage budget.")
    if car["is_project"] and project_count(player) >= rules["maximum_projects"]:
        errors.append("This garage has already reached the project limit.")

    if not rules["duplicates_allowed"]:
        normalised = re.sub(r"\s+", " ", car["name"].strip().lower())
        existing = {
            re.sub(r"\s+", " ", item["name"].strip().lower())
            for item in garage
        }
        if normalised in existing:
            errors.append("Duplicate vehicles are not allowed in this game.")

    return errors


def add_car_form(player: str) -> None:
    rules = st.session_state.rules
    garage = st.session_state.garages[player]

    with st.form(f"add_vehicle_{player}", clear_on_submit=True):
        st.write(f"### Add vehicle {len(garage) + 1} of {rules['vehicle_count']}")
        c1, c2 = st.columns(2)
        name = c1.text_input("Year, make and model", placeholder="1974 Alfa Romeo GTV")
        year = c1.number_input(
            "Year",
            min_value=1885,
            max_value=2100,
            value=max(rules["minimum_year"], min(rules["maximum_year"], 1980)),
            step=1,
        )
        price = c2.number_input(
            "Advertised price",
            min_value=0,
            max_value=int(rules["budget"]),
            step=500,
        )
        source_type = c2.selectbox("Advert type", ["Private", "Dealer", "Auction", "Other"])

        c1, c2 = st.columns(2)
        advert_link = c1.text_input("Advert link", placeholder="https://...")
        location = c2.text_input("Vehicle location", placeholder="Kent, UK")

        image = st.file_uploader(
            "Main vehicle image or advert screenshot",
            type=["png", "jpg", "jpeg", "webp"],
        )
        is_project = st.checkbox("This vehicle is a restoration project")
        notes = st.text_area(
            "Private notes",
            placeholder="Condition, risks, reason for choosing it, or checks needed.",
        )

        submitted = st.form_submit_button("Add to garage", type="primary")
        if submitted:
            car = {
                "name": name.strip(),
                "year": int(year),
                "price": float(price),
                "source_type": source_type,
                "advert_link": advert_link.strip(),
                "location": location.strip(),
                "is_project": bool(is_project),
                "notes": notes.strip(),
                "image_name": image.name if image else None,
                "image_bytes": image.getvalue() if image else None,
            }

            errors = validate_car(player, car)

            if source_type == "Dealer" and not rules["dealer_adverts_allowed"]:
                errors.append("Dealer adverts are not allowed.")
            if source_type == "Auction" and not rules["auction_adverts_allowed"]:
                errors.append("Auction listings are not allowed.")

            if errors:
                for error in errors:
                    st.error(error)
            else:
                st.session_state.garages[player].append(car)
                st.success(f"{car['name']} added.")
                st.rerun()


def car_card(player: str, index: int, reveal: bool = False) -> None:
    car = st.session_state.garages[player][index]
    with st.container(border=True):
        c1, c2 = st.columns([1, 2])
        with c1:
            if car.get("image_bytes"):
                st.image(car["image_bytes"], use_container_width=True)
            else:
                st.markdown("### 🚗")
                st.caption("No image uploaded")

        with c2:
            st.write(f"### {index + 1}. {car['name']}")
            details = [str(car["year"]), car.get("source_type", "")]
            if car.get("location"):
                details.append(car["location"])
            st.caption(" · ".join(filter(None, details)))

            if car.get("is_project"):
                st.warning("Restoration project")

            if reveal:
                st.info("Purchase price, advert and private notes are hidden.")
            else:
                st.metric("Purchase price", money(car["price"]))
                if car.get("advert_link"):
                    st.link_button("Open advert", car["advert_link"])
                if car.get("notes"):
                    st.write(car["notes"])
                if st.button("Remove", key=f"remove_{player}_{index}"):
                    st.session_state.garages[player].pop(index)
                    st.rerun()


def build_page() -> None:
    rule_summary()
    if not st.session_state.players:
        st.warning("Add players first.")
        return

    player = st.selectbox(
        "Player",
        st.session_state.players,
        index=st.session_state.players.index(st.session_state.active_builder),
    )
    st.session_state.active_builder = player

    rules = st.session_state.rules
    garage = st.session_state.garages[player]
    spent = total_spend(player)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vehicles", f"{len(garage)} / {rules['vehicle_count']}")
    c2.metric("Spent", money(spent))
    c3.metric("Remaining", money(rules["budget"] - spent))
    c4.metric("Projects", f"{project_count(player)} / {rules['maximum_projects']}")

    if len(garage) < rules["vehicle_count"]:
        add_car_form(player)
    else:
        st.success("This garage is complete.")

    st.divider()
    for index in range(len(garage)):
        car_card(player, index, reveal=False)

    st.divider()
    st.write("### Player progress")
    for name in st.session_state.players:
        complete = garage_complete(name)
        st.write(
            f"{'✅' if complete else '⏳'} **{name}** — "
            f"{len(st.session_state.garages[name])}/{rules['vehicle_count']} vehicles, "
            f"{money(total_spend(name))} spent"
        )

    if all_complete() and st.button("Lock garages and reveal", type="primary"):
        st.session_state.stage = "Reveal"
        st.rerun()


def reveal_page() -> None:
    rule_summary()
    if not all_complete():
        st.warning("Not every garage is complete yet.")

    player = st.selectbox("View garage", st.session_state.players)
    st.write(f"## {player}'s garage")

    for index in range(len(st.session_state.garages[player])):
        car_card(player, index, reveal=True)

    if all_complete() and st.button("Open valuation round", type="primary"):
        st.session_state.stage = "Valuation"
        st.rerun()


def valuation_page() -> None:
    rule_summary()
    st.header("Group valuation")
    st.caption("Enter the group's agreed market value for every vehicle.")

    for player in st.session_state.players:
        with st.expander(f"{player}'s garage", expanded=True):
            for index, car in enumerate(st.session_state.garages[player]):
                key = f"{player}::{index}"
                c1, c2 = st.columns([1, 2])
                with c1:
                    if car.get("image_bytes"):
                        st.image(car["image_bytes"], use_container_width=True)
                    else:
                        st.write("🚗")
                with c2:
                    st.write(f"**{car['name']}**")
                    valuation = st.number_input(
                        "Agreed value",
                        min_value=0,
                        step=500,
                        value=int(st.session_state.valuations.get(key, 0)),
                        key=f"valuation_{key}",
                    )
                    st.session_state.valuations[key] = float(valuation)

    if st.button("Calculate results", type="primary"):
        missing = [
            key
            for player in st.session_state.players
            for key in [
                f"{player}::{index}"
                for index in range(len(st.session_state.garages[player]))
            ]
            if st.session_state.valuations.get(key, 0) <= 0
        ]
        if missing:
            st.error("Every vehicle needs a valuation.")
        else:
            st.session_state.stage = "Results"
            st.rerun()


def results_page() -> None:
    rule_summary()
    rows = []
    for player in st.session_state.players:
        cost = total_spend(player)
        valuation = sum(
            st.session_state.valuations.get(f"{player}::{index}", 0)
            for index in range(len(st.session_state.garages[player]))
        )
        rows.append(
            {
                "Player": player,
                "Purchase total": cost,
                "Group valuation": valuation,
                "Virtual profit": valuation - cost,
            }
        )

    rows.sort(key=lambda row: row["Virtual profit"], reverse=True)

    if rows:
        winner = rows[0]
        st.success(
            f"🏆 {winner['Player']} wins with "
            f"{money(winner['Virtual profit'])} virtual profit."
        )

    for position, row in enumerate(rows, start=1):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Position", position)
            c2.metric("Player", row["Player"])
            c3.metric("Garage value", money(row["Group valuation"]))
            c4.metric("Profit / loss", money(row["Virtual profit"]))

    if st.button("Start a new game"):
        reset_game()
        st.rerun()


def sidebar() -> None:
    st.sidebar.title("Fantasy Garage")
    stages = ["Setup", "Build", "Reveal", "Valuation", "Results"]
    selected = st.sidebar.radio(
        "Game stage",
        stages,
        index=stages.index(st.session_state.stage),
    )
    st.session_state.stage = selected

    st.sidebar.divider()
    st.sidebar.caption(
        "This first beta stores data in the current Streamlit session. "
        "Closing or resetting the session may clear the game."
    )


init_state()
sidebar()

st.title("🏁 Fantasy Garage")
st.caption("Build the best fantasy vehicle collection within the organiser's rules.")

if st.session_state.stage == "Setup":
    setup_page()
elif st.session_state.stage == "Build":
    build_page()
elif st.session_state.stage == "Reveal":
    reveal_page()
elif st.session_state.stage == "Valuation":
    valuation_page()
else:
    results_page()
