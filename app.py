import hashlib
import hmac
import mimetypes
import secrets
import ipaddress
import json
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
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



def get_shortlist_items(game_id: str, player_id: str) -> List[Dict[str, Any]]:
    return (
        supabase.table("shortlist_items")
        .select("*")
        .eq("game_id", game_id)
        .eq("player_id", player_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )


def get_valuations(game_id: str) -> List[Dict[str, Any]]:
    return (
        supabase.table("valuations")
        .select("*")
        .eq("game_id", game_id)
        .execute()
        .data
        or []
    )



def is_safe_public_url(url: str) -> bool:
    """Allow only ordinary public HTTP(S) URLs."""
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False

        addresses = socket.getaddrinfo(parsed.hostname, None)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False
        return True
    except Exception:
        return False


def read_limited_response(response, max_bytes: int) -> bytes:
    chunks = []
    size = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        size += len(chunk)
        if size > max_bytes:
            raise ValueError("Remote file is too large.")
        chunks.append(chunk)
    return b"".join(chunks)


def extract_lead_image_url(advert_url: str) -> Optional[str]:
    """Best-effort extraction using common advert-page metadata."""
    if not is_safe_public_url(advert_url):
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; FantasyGarage/1.0; "
            "+https://streamlit.app)"
        )
    }

    try:
        with requests.get(
            advert_url,
            headers=headers,
            timeout=10,
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                return None
            html = read_limited_response(response, 2_000_000).decode(
                response.encoding or "utf-8",
                errors="replace",
            )

        soup = BeautifulSoup(html, "html.parser")
        candidates = []

        for attrs in (
            {"property": "og:image"},
            {"property": "og:image:secure_url"},
            {"name": "twitter:image"},
            {"name": "twitter:image:src"},
        ):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                candidates.append(tag["content"].strip())

        if not candidates:
            image = soup.find("img", src=True)
            if image:
                candidates.append(image["src"].strip())

        for candidate in candidates:
            resolved = urljoin(advert_url, candidate)
            if is_safe_public_url(resolved):
                return resolved
    except Exception:
        return None

    return None



def first_meta_content(soup: BeautifulSoup, selectors: List[Dict[str, str]]) -> str:
    for attrs in selectors:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def walk_json_ld(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json_ld(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json_ld(child)


def clean_vehicle_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title or "").strip()
    cleaned = re.sub(
        r"\s*[\|\-–—]\s*(for sale|used cars?|cars? for sale|marketplace).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned[:180]


def parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text_value = str(value).strip()
    if not text_value:
        return None

    matches = re.findall(r"\d[\d\s,.]*", text_value)
    if not matches:
        return None

    number = matches[0].replace(" ", "")
    if "," in number and "." in number:
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif "," in number:
        parts = number.split(",")
        if len(parts[-1]) in {1, 2}:
            number = number.replace(",", ".")
        else:
            number = number.replace(",", "")

    try:
        return float(number)
    except ValueError:
        return None


def infer_year(*values: Any) -> Optional[int]:
    for value in values:
        if value is None:
            continue
        match = re.search(r"\b(18[89]\d|19\d{2}|20\d{2}|2100)\b", str(value))
        if match:
            return int(match.group(1))
    return None


def extract_location_from_json(node: Dict[str, Any]) -> str:
    for key in ("availableAtOrFrom", "areaServed", "location", "address"):
        value = node.get(key)
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            address_parts = [
                value.get("addressLocality"),
                value.get("addressRegion"),
                value.get("addressCountry"),
                value.get("name"),
            ]
            location = ", ".join(
                str(part).strip() for part in address_parts if part
            )
            if location:
                return location
    return ""


def extract_listing_data(advert_url: str) -> Dict[str, Any]:
    """Best-effort importer using JSON-LD, Open Graph and page metadata."""
    result = {
        "vehicle_name": "",
        "vehicle_year": None,
        "advertised_price": None,
        "vehicle_location": "",
        "advert_type": "Private",
        "advert_description": "",
        "source_website": "",
        "source_image_url": "",
        "import_status": "failed",
    }

    if not is_safe_public_url(advert_url):
        return result

    parsed_url = urlparse(advert_url)
    result["source_website"] = parsed_url.netloc.lower().removeprefix("www.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; FantasyGarage/1.0; "
            "+https://streamlit.app)"
        )
    }

    try:
        with requests.get(
            advert_url,
            headers=headers,
            timeout=12,
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                return result

            html = read_limited_response(response, 3_000_000).decode(
                response.encoding or "utf-8",
                errors="replace",
            )
    except Exception:
        return result

    soup = BeautifulSoup(html, "html.parser")

    title = first_meta_content(
        soup,
        [
            {"property": "og:title"},
            {"name": "twitter:title"},
        ],
    )
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    description = first_meta_content(
        soup,
        [
            {"property": "og:description"},
            {"name": "description"},
            {"name": "twitter:description"},
        ],
    )
    image = extract_lead_image_url(advert_url) or ""

    price = None
    location = ""
    json_name = ""
    json_description = ""
    json_image = ""

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        for node in walk_json_ld(payload):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            types = {str(item).lower() for item in types if item}

            relevant = bool(
                types.intersection(
                    {
                        "product",
                        "vehicle",
                        "car",
                        "offer",
                        "individualproduct",
                        "itemlist",
                    }
                )
            )
            if not relevant:
                continue

            if not json_name and node.get("name"):
                json_name = str(node["name"]).strip()
            if not json_description and node.get("description"):
                json_description = str(node["description"]).strip()

            image_value = node.get("image")
            if not json_image and image_value:
                if isinstance(image_value, str):
                    json_image = image_value
                elif isinstance(image_value, list) and image_value:
                    first_image = image_value[0]
                    if isinstance(first_image, str):
                        json_image = first_image
                    elif isinstance(first_image, dict):
                        json_image = str(
                            first_image.get("url")
                            or first_image.get("contentUrl")
                            or ""
                        )
                elif isinstance(image_value, dict):
                    json_image = str(
                        image_value.get("url")
                        or image_value.get("contentUrl")
                        or ""
                    )

            offers = node.get("offers")
            offer_nodes = offers if isinstance(offers, list) else [offers]
            if "offer" in types:
                offer_nodes.append(node)

            for offer in offer_nodes:
                if not isinstance(offer, dict):
                    continue
                if price is None:
                    price = parse_number(
                        offer.get("price")
                        or offer.get("lowPrice")
                        or offer.get("highPrice")
                    )
                if not location:
                    location = extract_location_from_json(offer)

            if not location:
                location = extract_location_from_json(node)

    if not price:
        for selectors in (
            [{"property": "product:price:amount"}],
            [{"property": "og:price:amount"}],
            [{"name": "price"}],
            [{"itemprop": "price"}],
        ):
            value = first_meta_content(soup, selectors)
            if value:
                price = parse_number(value)
                if price is not None:
                    break

    final_name = clean_vehicle_title(json_name or title)
    final_description = (json_description or description or "").strip()[:3000]

    final_image = image or json_image
    if final_image:
        final_image = urljoin(advert_url, final_image)
        if not is_safe_public_url(final_image):
            final_image = ""

    year = infer_year(
        final_name,
        final_description,
        soup.get_text(" ", strip=True)[:10000],
    )

    site_text = result["source_website"]
    page_text = f"{final_name} {final_description}".lower()
    if any(word in site_text for word in ("auction", "collectingcars", "bonhams")):
        advert_type = "Auction"
    elif any(word in page_text for word in ("dealer", "dealership", "stock no")):
        advert_type = "Dealer"
    else:
        advert_type = "Private"

    populated = sum(
        [
            bool(final_name),
            price is not None,
            year is not None,
            bool(location),
            bool(final_description),
            bool(final_image),
        ]
    )

    result.update(
        {
            "vehicle_name": final_name,
            "vehicle_year": year,
            "advertised_price": price,
            "vehicle_location": location[:300],
            "advert_type": advert_type,
            "advert_description": final_description,
            "source_image_url": final_image,
            "import_status": "imported" if populated >= 4 else "partial",
        }
    )
    return result



def upload_remote_image(
    game_code: str,
    player_id: str,
    image_url: str,
) -> Optional[str]:
    """Download a public image and store it in the private Supabase bucket."""
    if not image_url or not is_safe_public_url(image_url):
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; FantasyGarage/1.0; "
            "+https://streamlit.app)"
        )
    }

    try:
        with requests.get(
            image_url,
            headers=headers,
            timeout=12,
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()
            mime = response.headers.get("content-type", "").split(";")[0].lower()
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                return None
            data = read_limited_response(response, 10_000_000)

        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }[mime]
        path = (
            f"{game_code}/{player_id}/"
            f"imported-{secrets.token_hex(8)}{extension}"
        )

        supabase.storage.from_(BUCKET_NAME).upload(
            path=path,
            file=data,
            file_options={"content-type": mime, "upsert": "true"},
        )
        return path
    except Exception:
        return None


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

    query_game = str(st.query_params.get("game", "")).strip().upper()
    query_player = str(st.query_params.get("player", "")).strip()

    with st.form("join_game"):
        code = st.text_input("Game code", value=query_game)
        name = st.text_input("Player name", value=query_player)
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
    st.query_params.clear()
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



@st.fragment(run_every="5s")
def live_shortlist(
    game: Dict[str, Any],
    player: Dict[str, Any],
) -> None:
    shortlist = get_shortlist_items(game["id"], player["id"])
    vehicles = get_vehicles(game["id"], player["id"])

    header_left, header_right = st.columns([3, 1])
    with header_left:
        st.subheader("Your shortlist")
        st.caption(
            "This list checks Supabase every five seconds while the page is open."
        )
    with header_right:
        if st.button(
            "Refresh now",
            key="refresh_live_shortlist",
            use_container_width=True,
        ):
            st.rerun(scope="fragment")

    if not shortlist:
        st.info(
            "No shortlisted vehicles yet. Cars sent from the browser extension "
            "will appear here automatically."
        )
        return

    for item in shortlist:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 1])

            with c1:
                image_url = item.get("source_image_url")
                image_path = item.get("image_path")

                if image_path:
                    stored_url = signed_image_url(image_path)
                    if stored_url:
                        st.image(stored_url, use_container_width=True)
                elif image_url:
                    st.image(image_url, use_container_width=True)

                st.write(f"**{item['vehicle_name']}**")
                details = [
                    str(item["vehicle_year"]) if item.get("vehicle_year") else "",
                    item.get("vehicle_location", ""),
                ]
                st.caption(" · ".join(filter(None, details)))

                if item.get("advert_url"):
                    st.link_button("Open advert", item["advert_url"])

            with c2:
                st.metric(
                    "Price",
                    money(game, item.get("advertised_price") or 0),
                )

                if item.get("advert_url") and not item.get("source_image_url"):
                    if st.button(
                        "Find advert image",
                        key=f"find_image_{item['id']}",
                        use_container_width=True,
                    ):
                        with st.spinner("Checking the advert page..."):
                            found_url = extract_lead_image_url(item["advert_url"])

                        if found_url:
                            supabase.table("shortlist_items").update(
                                {
                                    "source_image_url": found_url,
                                    "import_status": "partial",
                                }
                            ).eq("id", item["id"]).execute()
                            st.success("Lead image found.")
                            st.rerun(scope="fragment")
                        else:
                            st.warning(
                                "The advert did not expose a usable lead image."
                            )

                manual_image = st.file_uploader(
                    "Upload image",
                    type=["jpg", "jpeg", "png", "webp"],
                    key=f"shortlist_upload_{item['id']}",
                )

            with c3:
                add_disabled = (
                    player["garage_submitted"]
                    or len(vehicles) >= int(game["vehicle_count"])
                )

                if st.button(
                    "Add to garage",
                    key=f"promote_{item['id']}",
                    disabled=add_disabled,
                    use_container_width=True,
                ):
                    final_image_path = item.get("image_path")

                    if manual_image:
                        final_image_path = upload_image(
                            game["game_code"],
                            player["id"],
                            manual_image,
                        )
                    elif not final_image_path and item.get("source_image_url"):
                        with st.spinner("Saving the advert image..."):
                            final_image_path = upload_remote_image(
                                game["game_code"],
                                player["id"],
                                item["source_image_url"],
                            )

                    vehicle_data = {
                        "game_id": game["id"],
                        "player_id": player["id"],
                        "vehicle_name": item["vehicle_name"],
                        "vehicle_year": int(
                            item.get("vehicle_year") or game["minimum_year"]
                        ),
                        "purchase_price": float(
                            item.get("advertised_price") or 0
                        ),
                        "advert_type": item.get("advert_type") or "Private",
                        "advert_url": item.get("advert_url") or "",
                        "vehicle_location": item.get("vehicle_location") or "",
                        "is_project": bool(item.get("is_project")),
                        "private_notes": item.get("advert_description") or "",
                        "image_path": final_image_path,
                    }

                    errors = validate_vehicle(game, vehicles, vehicle_data)

                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        supabase.table("vehicles").insert(vehicle_data).execute()
                        supabase.table("shortlist_items").delete().eq(
                            "id", item["id"]
                        ).execute()
                        st.success("Vehicle moved to your garage.")
                        st.rerun()

                if st.button(
                    "Remove",
                    key=f"delete_shortlist_{item['id']}",
                    use_container_width=True,
                ):
                    supabase.table("shortlist_items").delete().eq(
                        "id", item["id"]
                    ).execute()
                    st.rerun(scope="fragment")


def build_garage(game: Dict[str, Any], player: Dict[str, Any]) -> None:
    stats = garage_stats(game, player["id"])
    vehicles = stats["vehicles"]
    shortlist = get_shortlist_items(game["id"], player["id"])

    rule_summary(game)
    st.header(f"{player['player_name']}'s garage")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Vehicles", f"{len(vehicles)} / {game['vehicle_count']}")
    c2.metric("Spent", money(game, stats["spent"]))
    c3.metric(
        "Remaining",
        money(game, float(game["total_budget"]) - stats["spent"]),
    )
    c4.metric("Shortlist", len(shortlist))

    if player["garage_submitted"]:
        st.success("Your garage is submitted and locked.")
    else:
        quick_tab, manual_tab = st.tabs(["Save to shortlist", "Add directly to garage"])

        with quick_tab:
            st.caption(
                "Paste the advert link, then either continue with quick manual "
                "entry or try the optional automatic importer."
            )

            import_key = f"imported_listing_{game['id']}_{player['id']}"

            with st.form("start_shortlist_capture"):
                shortlist_url = st.text_input(
                    "Advert URL",
                    placeholder="https://...",
                )
                c1, c2 = st.columns(2)
                quick_entry = c1.form_submit_button(
                    "Continue manually",
                    type="primary",
                    use_container_width=True,
                )
                try_import = c2.form_submit_button(
                    "Try to import details",
                    use_container_width=True,
                )

            if quick_entry or try_import:
                if not shortlist_url.strip():
                    st.error("Paste an advert URL first.")
                elif not is_safe_public_url(shortlist_url):
                    st.error("Enter a valid public http or https advert URL.")
                else:
                    if try_import:
                        with st.spinner("Trying to read the advert..."):
                            imported = extract_listing_data(shortlist_url.strip())
                        if imported["import_status"] == "failed":
                            st.info(
                                "This site blocked or did not expose its advert "
                                "details. Complete the quick form below instead."
                            )
                    else:
                        imported = {
                            "vehicle_name": "",
                            "vehicle_year": None,
                            "advertised_price": None,
                            "vehicle_location": "",
                            "advert_type": "Private",
                            "advert_description": "",
                            "source_website": urlparse(
                                shortlist_url.strip()
                            ).netloc.lower().removeprefix("www."),
                            "source_image_url": "",
                            "import_status": "manual",
                        }

                    imported["advert_url"] = shortlist_url.strip()
                    st.session_state[import_key] = imported
                    st.rerun()

            imported = st.session_state.get(import_key)

            if imported:
                imported_ok = imported.get("import_status") in {
                    "imported",
                    "partial",
                }
                st.subheader(
                    "Review imported advert"
                    if imported_ok
                    else "Quick shortlist entry"
                )

                image_url = imported.get("source_image_url")
                if image_url:
                    st.image(
                        image_url,
                        caption="Imported lead image",
                        width=420,
                    )

                default_year = imported.get("vehicle_year")
                if not default_year:
                    default_year = max(
                        int(game["minimum_year"]),
                        min(int(game["maximum_year"]), 1980),
                    )

                default_price = imported.get("advertised_price")
                if default_price is None:
                    default_price = 0

                advert_types = ["Private", "Dealer", "Auction", "Other"]
                imported_type = imported.get("advert_type") or "Private"
                type_index = (
                    advert_types.index(imported_type)
                    if imported_type in advert_types
                    else 0
                )

                with st.form("review_shortlist_capture"):
                    vehicle_name = st.text_input(
                        "Year, make and model",
                        value=imported.get("vehicle_name") or "",
                        placeholder="1974 Alfa Romeo GTV",
                    )

                    c1, c2 = st.columns(2)
                    advertised_price = c1.number_input(
                        "Advertised price",
                        min_value=0,
                        max_value=int(game["total_budget"]),
                        value=int(default_price),
                        step=500,
                    )
                    vehicle_year = c2.number_input(
                        "Year",
                        min_value=1885,
                        max_value=2100,
                        value=int(default_year),
                    )

                    shortlist_image = st.file_uploader(
                        "Upload the advert's main image or a screenshot",
                        type=["jpg", "jpeg", "png", "webp"],
                        help=(
                            "Recommended for sites that block automatic image "
                            "import. This image will follow the car into the garage."
                        ),
                    )

                    with st.expander("Optional details"):
                        c1, c2 = st.columns(2)
                        vehicle_location = c1.text_input(
                            "Location",
                            value=imported.get("vehicle_location") or "",
                        )
                        advert_type = c2.selectbox(
                            "Advert type",
                            advert_types,
                            index=type_index,
                        )
                        description = st.text_area(
                            "Advert description or notes",
                            value=imported.get("advert_description") or "",
                            height=100,
                        )
                        source_image_url = st.text_input(
                            "Imported image URL",
                            value=imported.get("source_image_url") or "",
                            help=(
                                "Optional. A manually uploaded screenshot takes "
                                "priority over this URL."
                            ),
                        )

                    c1, c2 = st.columns(2)
                    save_import = c1.form_submit_button(
                        "Save to shortlist",
                        type="primary",
                        use_container_width=True,
                    )
                    cancel_import = c2.form_submit_button(
                        "Cancel",
                        use_container_width=True,
                    )

                if cancel_import:
                    st.session_state.pop(import_key, None)
                    st.rerun()

                if save_import:
                    if not vehicle_name.strip():
                        st.error(
                            "Enter a vehicle name before saving it to the shortlist."
                        )
                    else:
                        image_path = None
                        if shortlist_image:
                            image_path = upload_image(
                                game["game_code"],
                                player["id"],
                                shortlist_image,
                            )

                        supabase.table("shortlist_items").insert(
                            {
                                "game_id": game["id"],
                                "player_id": player["id"],
                                "vehicle_name": vehicle_name.strip(),
                                "vehicle_year": int(vehicle_year),
                                "advertised_price": float(advertised_price),
                                "advert_url": imported.get("advert_url") or "",
                                "source_website": (
                                    imported.get("source_website") or ""
                                ),
                                "vehicle_location": vehicle_location.strip(),
                                "advert_description": description.strip(),
                                "advert_type": advert_type,
                                "is_project": False,
                                "image_path": image_path,
                                "source_image_url": source_image_url.strip(),
                                "import_status": imported.get(
                                    "import_status", "manual"
                                ),
                            }
                        ).execute()
                        st.session_state.pop(import_key, None)
                        st.success("Vehicle saved to your shortlist.")
                        st.rerun()

        with manual_tab:
            if len(vehicles) < int(game["vehicle_count"]):
                with st.form("add_vehicle", clear_on_submit=True):
                    st.subheader(f"Add vehicle {len(vehicles) + 1}")
                    c1, c2 = st.columns(2)
                    name = c1.text_input("Year, make and model")
                    price = c2.number_input(
                        "Advertised price",
                        min_value=0,
                        max_value=int(game["total_budget"]),
                        step=500,
                    )
                    advert_url = st.text_input("Advert URL")
                    image = st.file_uploader(
                        "Main image or advert screenshot",
                        type=["jpg", "jpeg", "png", "webp"],
                    )

                    with st.expander("Additional details"):
                        c1, c2 = st.columns(2)
                        year = c1.number_input(
                            "Year",
                            min_value=1885,
                            max_value=2100,
                            value=max(
                                int(game["minimum_year"]),
                                min(int(game["maximum_year"]), 1980),
                            ),
                        )
                        advert_type = c2.selectbox(
                            "Advert type",
                            ["Private", "Dealer", "Auction", "Other"],
                        )
                        location = st.text_input("Vehicle location")
                        is_project = st.checkbox("Restoration project")
                        notes = st.text_area("Private notes")

                    submitted = st.form_submit_button(
                        "Add to garage",
                        type="primary",
                    )

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
            else:
                st.info("Your garage already contains the required number of vehicles.")

    st.divider()
    live_shortlist(game, player)

    st.divider()
    st.subheader("Current garage")
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
