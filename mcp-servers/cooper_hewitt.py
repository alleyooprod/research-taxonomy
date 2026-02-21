# CUSTOM MCP SERVER — replace with official package when available
from fastmcp import FastMCP
import requests
import os

mcp = FastMCP("cooper-hewitt")

BASE_URL = "https://api.collection.cooperhewitt.org/rest/"
API_KEY = os.environ.get("COOPER_HEWITT_API_KEY", "")


def _call_api(method: str, params: dict | None = None) -> dict:
    """Make a GET request to the Cooper Hewitt API.

    Args:
        method: API method name (e.g. 'cooperhewitt.search.objects').
        params: Additional query parameters.

    Returns:
        Parsed JSON response dict.

    Raises:
        ValueError: If API key is not configured or API returns an error.
        requests.exceptions.RequestException: On network failure.
    """
    if not API_KEY:
        raise ValueError(
            "COOPER_HEWITT_API_KEY environment variable is not set. "
            "Get a free API key at https://collection.cooperhewitt.org/api/ "
            "and set it: export COOPER_HEWITT_API_KEY=your_key_here"
        )

    request_params = {
        "method": method,
        "access_token": API_KEY,
    }
    if params:
        request_params.update(params)

    resp = requests.get(BASE_URL, params=request_params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("stat") != "ok":
        error_msg = data.get("error", {}).get("message", "Unknown API error")
        error_code = data.get("error", {}).get("code", "")
        raise ValueError(f"Cooper Hewitt API error {error_code}: {error_msg}")

    return data


def _extract_designer(obj: dict) -> str:
    """Extract primary designer name from an object's participants list."""
    participants = obj.get("participants", [])
    if isinstance(participants, list):
        for p in participants:
            if isinstance(p, dict):
                role = p.get("role_name", "").lower()
                if role in ("designer", "maker", "artist", "architect", "manufacturer"):
                    return f"{p.get('person_name', 'Unknown')} ({p.get('role_name', '')})"
        # Fall back to first participant if no designer role found
        if participants and isinstance(participants[0], dict):
            return f"{participants[0].get('person_name', 'Unknown')} ({participants[0].get('role_name', '')})"
    return "Unknown"


def _get_image_url(obj: dict) -> str:
    """Extract the best available image URL from an object.

    Prefers medium-size ('z') image, falls back through sizes.
    """
    images = obj.get("images", [])
    if isinstance(images, list) and images:
        img = images[0]
    elif isinstance(images, dict):
        # Sometimes images is a dict with a single entry
        img = next(iter(images.values()), {}) if images else {}
    else:
        return ""

    if not isinstance(img, dict):
        return ""

    # Try sizes in preference order: z (medium), n (small), b (large), sq (square)
    for size in ("z", "n", "b", "sq", "d", "k", "o"):
        url = img.get(size, {}).get("url", "") if isinstance(img.get(size), dict) else ""
        if url:
            return url

    # Some objects have a flat 'url' key
    return img.get("url", "")


def _format_object_summary(obj: dict) -> str:
    """Format an object as a concise summary line for search results."""
    title = obj.get("title_raw") or obj.get("title") or "Untitled"
    date = obj.get("date", "n.d.")
    obj_type = obj.get("type", "Unknown type")
    designer = _extract_designer(obj)
    image_url = _get_image_url(obj)
    permalink = obj.get("url", "")
    obj_id = obj.get("id", "")

    lines = [f"  Title: {title}"]
    lines.append(f"  ID: {obj_id}")
    lines.append(f"  Date: {date}")
    lines.append(f"  Type: {obj_type}")
    lines.append(f"  Designer: {designer}")
    if image_url:
        lines.append(f"  Image: {image_url}")
    if permalink:
        lines.append(f"  Link: {permalink}")
    return "\n".join(lines)


def _format_object_detail(obj: dict) -> str:
    """Format an object with full metadata."""
    title = obj.get("title_raw") or obj.get("title") or "Untitled"
    obj_id = obj.get("id", "")
    date = obj.get("date", "n.d.")
    medium = obj.get("medium", "")
    dimensions = obj.get("dimensions", "")
    obj_type = obj.get("type", "Unknown type")
    description = obj.get("description", "")
    permalink = obj.get("url", "")
    department = obj.get("department_id", "")
    credit_line = obj.get("creditline", "")

    lines = [
        f"Title: {title}",
        f"ID: {obj_id}",
        f"Date: {date}",
        f"Type: {obj_type}",
    ]

    if medium:
        lines.append(f"Medium: {medium}")
    if dimensions:
        lines.append(f"Dimensions: {dimensions}")
    if credit_line:
        lines.append(f"Credit: {credit_line}")

    # People / participants
    participants = obj.get("participants", [])
    if isinstance(participants, list) and participants:
        lines.append("")
        lines.append("People:")
        for p in participants:
            if isinstance(p, dict):
                name = p.get("person_name", "Unknown")
                role = p.get("role_name", "")
                person_id = p.get("person_id", "")
                lines.append(f"  - {name} ({role}) [ID: {person_id}]")

    # Images
    images = obj.get("images", [])
    image_list = []
    if isinstance(images, list):
        image_list = images
    elif isinstance(images, dict):
        image_list = list(images.values())

    if image_list:
        lines.append("")
        lines.append("Images:")
        for img in image_list[:3]:  # Limit to 3 images
            if isinstance(img, dict):
                for size in ("z", "b", "n"):
                    url = img.get(size, {}).get("url", "") if isinstance(img.get(size), dict) else ""
                    if url:
                        lines.append(f"  - {url}")
                        break

    if description:
        lines.append("")
        lines.append(f"Description: {description}")

    if permalink:
        lines.append("")
        lines.append(f"Permalink: {permalink}")

    return "\n".join(lines)


@mcp.tool()
def cooperhewitt_search(
    query: str,
    has_images: bool = True,
    page: int = 1,
    per_page: int = 10,
) -> str:
    """Search the Cooper Hewitt Smithsonian Design Museum collection (215,000+ design objects).

    Covers 30 centuries of design: furniture, textiles, posters, product design, jewelry,
    drawings, prints, wallcoverings, and more.

    Args:
        query: Search terms (e.g. "Art Deco poster", "Charles Eames chair", "Japanese textile").
        has_images: Only return objects with images (default True).
        page: Page number for pagination (default 1).
        per_page: Results per page, 1-100 (default 10).

    Returns:
        Formatted list of matching design objects with title, date, type, designer,
        image URL, and permalink.
    """
    per_page = max(1, min(100, per_page))

    params = {
        "query": query,
        "has_images": "1" if has_images else "0",
        "page": str(page),
        "per_page": str(per_page),
    }

    try:
        data = _call_api("cooperhewitt.search.objects", params)
    except ValueError as e:
        return f"Error: {e}"
    except requests.exceptions.Timeout:
        return "Error: Request to Cooper Hewitt API timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to Cooper Hewitt API. Check network connection."
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    objects = data.get("objects", [])
    total = data.get("total", 0)
    pages = data.get("pages", 0)

    if not objects:
        return f'No results found for "{query}".'

    lines = [
        f'Cooper Hewitt — Search results for "{query}"',
        f"Total: {total} objects (page {page} of {pages})",
        "=" * 60,
    ]

    for i, obj in enumerate(objects, start=1):
        lines.append("")
        lines.append(f"[{i}]")
        lines.append(_format_object_summary(obj))

    return "\n".join(lines)


@mcp.tool()
def cooperhewitt_get_object(object_id: str) -> str:
    """Get full details for a specific Cooper Hewitt design object.

    Args:
        object_id: The Cooper Hewitt object ID (e.g. "18382391").

    Returns:
        Complete object metadata including title, date, medium, dimensions,
        type, designers, images, and description.
    """
    if not object_id or not object_id.strip():
        return "Error: object_id is required."

    try:
        data = _call_api("cooperhewitt.objects.getInfo", {"object_id": object_id.strip()})
    except ValueError as e:
        return f"Error: {e}"
    except requests.exceptions.Timeout:
        return "Error: Request to Cooper Hewitt API timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to Cooper Hewitt API. Check network connection."
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    obj = data.get("object", {})
    if not obj:
        return f"No object found with ID {object_id}."

    header = "Cooper Hewitt — Object Detail\n" + "=" * 40 + "\n"
    return header + _format_object_detail(obj)


@mcp.tool()
def cooperhewitt_get_random(has_images: bool = True) -> str:
    """Get a random design object from the Cooper Hewitt collection for inspiration.

    Useful for discovering unexpected design objects across 30 centuries of design history.

    Args:
        has_images: Only return objects with images (default True).

    Returns:
        Full metadata for a randomly selected design object.
    """
    params = {"has_images": "1" if has_images else "0"}

    try:
        data = _call_api("cooperhewitt.objects.getRandom", params)
    except ValueError as e:
        return f"Error: {e}"
    except requests.exceptions.Timeout:
        return "Error: Request to Cooper Hewitt API timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to Cooper Hewitt API. Check network connection."
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    obj = data.get("object", {})
    if not obj:
        return "No random object returned. Try again."

    header = "Cooper Hewitt — Random Design Object\n" + "=" * 40 + "\n"
    return header + _format_object_detail(obj)


@mcp.tool()
def cooperhewitt_search_designers(query: str) -> str:
    """Search for designers, makers, and manufacturers in the Cooper Hewitt collection.

    Args:
        query: Search terms for designer name (e.g. "Ray Eames", "William Morris", "Noguchi").

    Returns:
        List of matching people with name, ID, and object count.
    """
    if not query or not query.strip():
        return "Error: query is required."

    try:
        data = _call_api("cooperhewitt.search.people", {"query": query.strip()})
    except ValueError as e:
        return f"Error: {e}"
    except requests.exceptions.Timeout:
        return "Error: Request to Cooper Hewitt API timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to Cooper Hewitt API. Check network connection."
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    people = data.get("people", [])
    total = data.get("total", 0)

    if not people:
        return f'No designers found matching "{query}".'

    lines = [
        f'Cooper Hewitt — Designer search for "{query}"',
        f"Total: {total} results",
        "=" * 60,
        "",
    ]

    for i, person in enumerate(people, start=1):
        name = person.get("name", "Unknown")
        person_id = person.get("id", "")
        count = person.get("count", person.get("object_count", ""))
        url = person.get("url", "")

        lines.append(f"[{i}] {name}")
        lines.append(f"    ID: {person_id}")
        if count:
            lines.append(f"    Objects: {count}")
        if url:
            lines.append(f"    Link: {url}")
        lines.append("")

    lines.append("Use cooperhewitt_search() with a designer name to see their objects.")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
