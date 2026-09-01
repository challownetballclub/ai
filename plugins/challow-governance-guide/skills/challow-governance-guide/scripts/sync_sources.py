#!/usr/bin/env python3
"""Synchronize the public Challow governance sources into this skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.error import URLError
from urllib.request import Request, urlopen


HUB_URL = "https://www.challownetballclub.org.uk/ai/governance.md"
ALLOWED_HOST = "www.challownetballclub.org.uk"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def fetch(url: str) -> tuple[bytes, str, str]:
    last_error: Exception | None = None
    for attempt in range(3):
        request = Request(url, headers={"User-Agent": "ChallowGovernanceSync/1.0"})
        try:
            with urlopen(request, timeout=20) as response:
                final_url = response.geturl()
                parsed = urlsplit(final_url)
                if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
                    raise ValueError(f"Refused redirect outside the approved HTTPS host: {final_url}")
                content = response.read(MAX_SOURCE_BYTES + 1)
                if len(content) > MAX_SOURCE_BYTES:
                    raise ValueError(f"Source exceeds {MAX_SOURCE_BYTES} bytes: {url}")
                return content, final_url, response.headers.get_content_type()
        except (TimeoutError, URLError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to fetch after 3 attempts: {url}") from last_error


def normalize_markdown(raw: bytes, url: str) -> bytes:
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError(f"Empty Markdown source: {url}")
    return (text.rstrip() + "\n").encode("utf-8")


def normalize_json(raw: bytes, url: str) -> bytes:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON source: {url}") from exc
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def is_public_json(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.path == "/api/content":
        return True
    return parsed.path == "/api/governance" and parse_qs(parsed.query).get("scope") == ["public"]


def output_path_for(url: str) -> Path:
    parsed = urlsplit(url)
    if url == HUB_URL:
        return Path("sources/governance.md")
    if parsed.path.endswith(".md"):
        return Path("sources") / Path(parsed.path).name
    if parsed.path == "/api/content":
        return Path("data/current-content.json")
    if parsed.path == "/api/governance":
        return Path("data/governance-public.json")
    raise ValueError(f"Unsupported source URL: {url}")


def discover_sources(hub_markdown: str) -> list[tuple[str, str, str]]:
    sources = [("Governance source hub", HUB_URL, "markdown")]
    seen = {HUB_URL}
    for title, href in LINK_PATTERN.findall(hub_markdown):
        url = urljoin(HUB_URL, href.strip())
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST or url in seen:
            continue
        if parsed.path.endswith(".md"):
            kind = "markdown"
        elif is_public_json(url):
            kind = "json"
        else:
            continue
        seen.add(url)
        sources.append((title.strip(), url, kind))
    return sources


def write_if_changed(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)
    return True


def clean_stale_files(root: Path, expected: set[Path]) -> bool:
    changed = False
    for directory_name in ("sources", "data"):
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in directory.iterdir():
            relative = path.relative_to(root)
            if path.is_file() and relative not in expected:
                path.unlink()
                changed = True
    return changed


def content_digest(documents: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for document in documents:
        digest.update(document["url"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(document["sha256"].encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def update_plugin_version(manifest_path: Path, digest: str) -> bool:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_version = payload["version"].split("+", 1)[0]
    version = f"{base_version}+codex.sources-{digest[:12]}"
    if payload["version"] == version:
        return False
    payload["version"] = version
    content = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return write_if_changed(manifest_path, content)


def synchronize(output_root: Path, plugin_manifest: Path) -> tuple[bool, dict[str, object]]:
    hub_raw, hub_final_url, hub_content_type = fetch(HUB_URL)
    hub_content = normalize_markdown(hub_raw, HUB_URL)
    hub_text = hub_content.decode("utf-8")
    discovered = discover_sources(hub_text)
    if len(discovered) < 2:
        raise ValueError("The governance hub did not expose any approved linked sources")

    def prepare_source(source: tuple[str, str, str]) -> tuple[dict[str, str], Path, bytes]:
        title, url, kind = source
        if url == HUB_URL:
            raw, final_url, content_type = hub_raw, hub_final_url, hub_content_type
            content = hub_content
        else:
            raw, final_url, content_type = fetch(url)
            content = normalize_markdown(raw, url) if kind == "markdown" else normalize_json(raw, url)
        relative_path = output_path_for(url)
        document = {
            "title": title,
            "url": url,
            "final_url": final_url,
            "kind": kind,
            "content_type": content_type,
            "path": relative_path.as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        return document, relative_path, content

    with ThreadPoolExecutor(max_workers=4) as executor:
        prepared = list(executor.map(prepare_source, discovered))

    documents: list[dict[str, str]] = []
    expected: set[Path] = set()
    changed = False
    for document, relative_path, content in prepared:
        if relative_path in expected:
            raise ValueError(f"Two sources resolve to the same output path: {relative_path}")
        expected.add(relative_path)
        changed = write_if_changed(output_root / relative_path, content) or changed
        documents.append(document)

    digest = content_digest(documents)
    manifest_path = output_root / "source-manifest.json"
    previous: dict[str, object] = {}
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    synced_at = previous.get("synced_at") if previous.get("content_digest") == digest else None
    if not isinstance(synced_at, str):
        synced_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    manifest: dict[str, object] = {
        "schema_version": 1,
        "hub_url": HUB_URL,
        "synced_at": synced_at,
        "content_digest": digest,
        "documents": documents,
    }
    manifest_content = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    changed = write_if_changed(manifest_path, manifest_content) or changed
    changed = clean_stale_files(output_root, expected) or changed
    changed = update_plugin_version(plugin_manifest, digest) or changed
    return changed, manifest


def parse_args() -> argparse.Namespace:
    skill_root = Path(__file__).resolve().parent.parent
    plugin_root = skill_root.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=skill_root / "references")
    parser.add_argument(
        "--plugin-manifest",
        type=Path,
        default=plugin_root / ".codex-plugin" / "plugin.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    changed, manifest = synchronize(args.output.resolve(), args.plugin_manifest.resolve())
    status = "updated" if changed else "unchanged"
    print(f"Governance snapshot {status}: {len(manifest['documents'])} sources")
    print(f"Content digest: {manifest['content_digest']}")


if __name__ == "__main__":
    main()
