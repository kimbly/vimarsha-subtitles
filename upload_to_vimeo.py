import argparse
import os
import sys
from typing import Optional

import requests


LANGUAGE_NAME_TO_ISO_639_1 = {
    "arabic": "ar",
    "bengali": "bn",
    "chinese": "zh",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "gujarati": "gu",
    "hausa": "ha",
    "hindi": "hi",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "kannada": "kn",
    "kashmiri": "ks",
    "korean": "ko",
    "marathi": "mr",
    "nepali": "ne",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "russian": "ru",
    "spanish": "es",
    "swahili": "sw",
    "tamil": "ta",
    "telugu": "te",
    "tibetan": "bo",
    "thai": "th",
    "turkish": "tr",
    "urdu": "ur",
    "vietnamese": "vi",
    "yoruba": "yo",
}


def normalize_language_code(language: str) -> str:
    if language is None:
        raise ValueError("Language is required.")

    normalized = language.strip().lower()
    if not normalized:
        raise ValueError("Language is required.")

    if normalized in LANGUAGE_NAME_TO_ISO_639_1:
        return LANGUAGE_NAME_TO_ISO_639_1[normalized]

    valid_iso_codes = set(LANGUAGE_NAME_TO_ISO_639_1.values())
    if normalized in valid_iso_codes:
        return normalized

    supported_names = ", ".join(sorted(LANGUAGE_NAME_TO_ISO_639_1))
    raise ValueError(
        f"Unsupported language '{language}'. Supported language names are: {supported_names}. "
        "To add a new language, add the normal language name and its ISO 639-1 code to the LANGUAGE_NAME_TO_ISO_639_1 table in this script."
    )


def vimeo_get(url: str, **kwargs) -> requests.Response:
    max_retries = 5

    for attempt in range(max_retries + 1):
        response = requests.get(url, **kwargs)
        if response.status_code != 429:
            return response

        if attempt == max_retries:
            response.raise_for_status()

        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else min(60, 2**attempt)
        except ValueError:
            delay = min(60, 2**attempt)

        time.sleep(max(0, delay))

    raise RuntimeError("Vimeo request retry loop ended unexpectedly")


def get_vimeo_video_id(video_name: str, access_token: str) -> str:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.vimeo.*+json;version=3.4",
    }
    videos = []
    seen_uris = set()

    def collect_videos(url: str, params: Optional[dict] = None) -> None:
        while url:
            response = vimeo_get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()

            for video in payload.get("data", []):
                uri = video.get("uri")
                if uri and uri not in seen_uris:
                    seen_uris.add(uri)
                    videos.append(video)

            url = (payload.get("paging") or {}).get("next")
            params = None

    # Videos uploaded by the authenticated user.
    collect_videos("https://api.vimeo.com/me/videos", {"per_page": 100})

    # Videos shared with the authenticated user.
    collect_videos(
        "https://api.vimeo.com/me/videos",
        {"filter": "shared", "per_page": 100},
    )

    teams_response = vimeo_get(
        "https://api.vimeo.com/me/teams",
        headers=headers,
        params={"per_page": 100},
        timeout=30,
    )
    if teams_response.status_code != 404:
        teams_response.raise_for_status()
        for team in teams_response.json().get("data", []):
            team_uri = team.get("uri", "")
            if team_uri:
                collect_videos(
                    f"https://api.vimeo.com{team_uri}/videos",
                    {"per_page": 100},
                )

    for video in videos:
        if video.get("name") == video_name:
            return video["uri"].split("/")[-1]

    known_videos = [video["name"] for video in videos if video.get("name")]
    if known_videos:
        print(
            f"No Vimeo video found with name: '{video_name}'. "
            f"Known videos: {', '.join(known_videos)}",
            file=sys.stderr,
        )
    else:
        print(
            "No videos were found for this account, including shared videos.",
            file=sys.stderr,
        )

    raise ValueError(f"No Vimeo video found with name: {video_name}")


def get_vimeo_team_id_for_video(video_id: str, access_token: str) -> Optional[str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.vimeo.*+json;version=3.4",
    }

    response = vimeo_get(
        f"https://api.vimeo.com/videos/{video_id}",
        headers=headers,
        timeout=30,
    )
    if response.status_code == 404:
        raise ValueError(f"No Vimeo video found with id: {video_id}")
    response.raise_for_status()

    video = response.json()
    owner = video.get("owner") or video.get("user") or {}
    owner_type = owner.get("type")
    if owner_type == "team":
        owner_uri = owner.get("uri") or ""
        return owner_uri.split("/")[-1] or None

    teams_response = vimeo_get(
        "https://api.vimeo.com/me/teams",
        headers=headers,
        params={"per_page": 100},
        timeout=30,
    )
    if teams_response.status_code == 404:
        return None
    teams_response.raise_for_status()

    teams = teams_response.json().get("data", [])
    if len(teams) == 1:
        return teams[0]["uri"].split("/")[-1]

    return None


def upload_vtt_subtitles(
    video_reference: str,
    vtt_file_path: str,
    language: str,
    access_token: str,
) -> None:
    if not os.path.exists(vtt_file_path):
        raise FileNotFoundError(f"VTT file not found: {vtt_file_path}")

    resolved_language = normalize_language_code(language)

    if video_reference.isdigit():
        resolved_video_id = video_reference
        team_id = get_vimeo_team_id_for_video(video_reference, access_token)
        target_name = video_reference
    else:
        resolved_video_id = get_vimeo_video_id(video_reference, access_token)
        team_id = get_vimeo_team_id_for_video(resolved_video_id, access_token)
        target_name = video_reference

    with open(vtt_file_path, "rb") as f:
        subtitle_bytes = f.read()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.vimeo.*+json;version=3.4",
    }

    track_data = {
        "language": resolved_language,
        "name": os.path.splitext(os.path.basename(vtt_file_path))[0],
        "type": "subtitles",
    }

    params = {}
    if team_id:
        params["team_id"] = team_id

    video_response = vimeo_get(
        f"https://api.vimeo.com/videos/{resolved_video_id}",
        headers=headers,
        params=params,
        timeout=60,
    )
    video_response.raise_for_status()
    video = video_response.json()
    texttracks_uri = (
        video.get("metadata", {})
        .get("connections", {})
        .get("texttracks", {})
        .get("uri")
    )
    if not texttracks_uri:
        raise ValueError("Vimeo video response did not include metadata.connections.texttracks.uri")

    track_response = requests.post(
        f"https://api.vimeo.com{texttracks_uri}",
        headers=headers,
        params=params,
        json=track_data,
        timeout=60,
    )
    track_response.raise_for_status()
    upload_link = track_response.json().get("link")
    if not upload_link:
        raise ValueError("Vimeo text track response did not include an upload link")

    upload_response = requests.put(
        upload_link,
        headers={"Content-Type": "text/vtt"},
        data=subtitle_bytes,
        timeout=60,
    )
    upload_response.raise_for_status()
    print(f"Uploaded subtitles for '{target_name}' in language '{resolved_language}'")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload a VTT subtitle file to a Vimeo video."
    )
    parser.add_argument("video_reference", nargs="?", help="Name or ID of the Vimeo video")
    parser.add_argument("vtt_file", help="Path to the VTT subtitle file")
    parser.add_argument("language", help="Subtitle language name or ISO 639-1 code, e.g. hindi, spanish, hi, es")
    parser.add_argument(
        "--access-token",
        default=None,
        help="Vimeo access token. Can also be set as VIMEO_ACCESS_TOKEN.",
    )
    args = parser.parse_args()

    access_token = args.access_token or os.environ.get("VIMEO_ACCESS_TOKEN")

    if not access_token:
        print(
            "Error: Vimeo access token is required. Pass --access-token or set VIMEO_ACCESS_TOKEN.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not args.video_reference:
        parser.error("A Vimeo video name or ID is required.")

    try:
        upload_vtt_subtitles(args.video_reference, args.vtt_file, args.language, access_token)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
