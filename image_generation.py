from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image

RUNWARE_ENDPOINT = "https://api.runware.ai/v1"
MANIFEST_NAME = "image_generation_manifest.json"


@dataclass(frozen=True)
class ModelProfile:
    key: str
    display_name: str
    provider: str
    model_id: str
    prompt_enhancer: str = "generic"
    dimensions: tuple[int, int] = (1280, 720)
    text_rendering: bool = False
    recommended: bool = False
    defaults: dict[str, Any] = field(default_factory=dict)
    cost_per_image: float | None = None


# Registry is deliberately data-shaped: adding a model does not change generation logic.
MODEL_PROFILES: dict[str, ModelProfile] = {
    "p-image-ideogram": ModelProfile(
        key="p-image-ideogram",
        display_name="P-Image-Ideogram",
        provider="Runware",
        model_id="prunaai:p-image@ideogram",
        prompt_enhancer="p_image_ideogram",
        dimensions=(1280, 720),
        text_rendering=True,
        recommended=True,
        defaults={"outputFormat": "PNG", "numberResults": 1},
    ),
    "flux-1-schnell": ModelProfile(
        key="flux-1-schnell",
        display_name="FLUX.1 Schnell",
        provider="Runware",
        model_id="runware:100@1",
        prompt_enhancer="generic",
        dimensions=(1344, 768),
        text_rendering=False,
        defaults={"outputFormat": "PNG", "numberResults": 1},
    ),
}
DEFAULT_MODEL_KEY = "p-image-ideogram"


@dataclass(frozen=True)
class ImageAssignment:
    image_number: int
    filename: str
    image_prompt_id: str
    scene_id: str
    original_prompt: str
    narration_context: str
    asset_path: Path

    @property
    def original_prompt_hash(self) -> str:
        return sha256_text(self.original_prompt)


@dataclass
class GenerationResult:
    assignment: ImageAssignment
    status: str
    attempts: int
    error: str = ""
    elapsed_seconds: float = 0.0
    enhanced_prompt: str = ""
    dimensions: tuple[int, int] | None = None
    cost: float | None = None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def model_profiles_from_config(config: dict[str, Any] | None = None) -> dict[str, ModelProfile]:
    profiles = dict(MODEL_PROFILES)
    for raw in (config or {}).get("image_generation_models", []):
        try:
            key = str(raw["key"])
            dims = raw.get("dimensions", [1280, 720])
            profiles[key] = ModelProfile(
                key=key,
                display_name=str(raw.get("display_name", key)),
                provider=str(raw.get("provider", "Runware")),
                model_id=str(raw["model_id"]),
                prompt_enhancer=str(raw.get("prompt_enhancer", "generic")),
                dimensions=(int(dims[0]), int(dims[1])),
                text_rendering=bool(raw.get("text_rendering", False)),
                recommended=bool(raw.get("recommended", False)),
                defaults=dict(raw.get("provider_parameters", {})),
                cost_per_image=float(raw["cost_per_image"]) if raw.get("cost_per_image") is not None else None,
            )
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return profiles


def _field(block: str, label: str) -> str:
    match = re.search(rf"(?mi)^- {re.escape(label)}:\s*(.*)$", block)
    return match.group(1).strip() if match else ""


def _production_image_asset_contract(project: Path) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Mirror the existing Production -> Timeline filename contract without modifying it.

    07_production_sheet.csv is authoritative for AI-image assignment order.  The existing
    timeline builder uses selected_asset_path when present; otherwise it resolves assignment
    N to assets/images/image_NNN.png.  This downstream helper mirrors that behavior so a
    differently padded Filename field in 10_image_prompts.md cannot create a second alias.
    """
    sheet = project / "07_production_sheet.csv"
    if not sheet.is_file():
        return [], {}
    with sheet.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ordered: list[tuple[str, str]] = []
    by_prompt_id: dict[str, str] = {}
    image_index = 0
    for row in rows:
        asset_type = str(row.get("recommended_asset_type") or row.get("asset_type") or "").strip().upper()
        if asset_type != "AI_IMAGE":
            continue
        image_index += 1
        prompt_id = str(row.get("image_prompt_id") or "").strip()
        selected = str(row.get("selected_asset_path") or "").strip().replace("\\", "/")
        reference = selected or f"assets/images/image_{image_index:03d}.png"
        ordered.append((prompt_id, reference))
        if prompt_id:
            by_prompt_id[prompt_id] = reference
    return ordered, by_prompt_id


def _resolve_contract_asset_path(project: Path, reference: str) -> Path:
    raw = str(reference).strip().replace("\\", "/")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (project / path).resolve()


def load_production_image_assignments(project: Path) -> list[ImageAssignment]:
    """Read immutable prompts while consuming the existing Production/CapCut filename contract.

    The Filename field in 10_image_prompts.md is preserved on disk and is never rewritten.
    When 07_production_sheet.csv is available, the asset filename/path is normalized only in
    this downstream layer to exactly what the existing timeline builder will resolve.
    """
    project = Path(project).resolve()
    prompt_path = project / "10_image_prompts.md"
    if not prompt_path.is_file():
        return []
    text = prompt_path.read_text(encoding="utf-8-sig")
    matches = list(re.finditer(r"(?m)^### IMAGE\s+(\d+)\s*$", text))
    contract_order, contract_by_prompt = _production_image_asset_contract(project)
    assignments: list[ImageAssignment] = []
    for i, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[match.end():end]
        source_filename = _field(block, "Filename")
        prompt_id = _field(block, "image_prompt_id")

        contract_reference = contract_by_prompt.get(prompt_id, "") if prompt_id else ""
        if not contract_reference and i < len(contract_order):
            contract_reference = contract_order[i][1]

        if contract_reference:
            asset_path = _resolve_contract_asset_path(project, contract_reference)
            filename = asset_path.name
        else:
            # Compatibility fallback for older projects lacking 07_production_sheet.csv:
            # accept the Production-supplied zero padding instead of imposing :03d.
            filename = source_filename or f"image_{number:03d}.png"
            if Path(filename).name != filename or not re.fullmatch(r"image_\d+\.png", filename, re.IGNORECASE):
                raise ValueError(f"IMAGE {number:03d} has an invalid image filename mapping: {filename}")
            asset_path = project / "assets" / "images" / filename

        prompt = _field(block, "Final AI IMAGE PROMPT")
        if not prompt:
            raise ValueError(f"IMAGE {number:03d} is missing Final AI IMAGE PROMPT")
        context = " ".join(filter(None, [_field(block, "Script Context"), _field(block, "Narrative Context")]))
        assignments.append(ImageAssignment(
            image_number=number,
            filename=filename,
            image_prompt_id=prompt_id,
            scene_id=_field(block, "Scene ID"),
            original_prompt=prompt,
            narration_context=context,
            asset_path=asset_path,
        ))
    return assignments


def _has_readable_text_requirement(prompt: str) -> bool:
    low = prompt.lower()
    if "no embedded readable text" in low or "blank notebook" in low or "blank screen" in low:
        return False
    return any(token in low for token in ("readable text", "text that says", "sign reads", "label reads", "exact text"))


def enhance_prompt(original_prompt: str, profile: ModelProfile, enabled: bool = True) -> str:
    if not enabled:
        return original_prompt
    if profile.prompt_enhancer != "p_image_ideogram":
        return original_prompt
    low = original_prompt.lower()
    additions = [
        "Generation clarity: keep one dominant visual idea, one primary human action, and a clean 16:9 documentary composition suitable for editor-applied motion.",
        "Keep important foreground objects spatially distinct and avoid unnecessary duplicate props.",
    ]
    complex_action = any(x in low for x in ("hand", "holding", "pour", "spoon", "grip", "reach", "cut", "open", "close", "lift"))
    if complex_action:
        additions.append("Render hand-object contact literally and physically plausibly, with natural fingers, joints, posture, and clear source-to-action-to-destination relationships where movement or liquid is involved.")
    if "blank notebook" in low or "blank screen" in low or "no embedded readable text" in low:
        additions.append("Do not generate pseudo-text, accidental letters, captions, labels, watermarks, or interface-like writing.")
    elif _has_readable_text_requirement(original_prompt):
        additions.append("Render only the exact readable text explicitly requested in the original prompt; do not add any other text.")
    additions.append("Preserve the original scene meaning, senior age detail, non-clinical documentary realism, safety boundaries, and medical-claim limits exactly; do not invent outcomes, mechanisms, authority, or before/after effects.")
    candidate = original_prompt.rstrip() + "\n\n" + " ".join(additions)
    return candidate if enhanced_prompt_is_safe(original_prompt, candidate) else original_prompt


_FORBIDDEN_ADDITIONS = (
    "cure", "cures", "miracle", "diagnose", "diagnosis", "guaranteed", "clinically proven",
    "doctor recommends", "doctor recommended", "surgeon recommends", "before and after",
    "treats", "treatment result", "regenerates", "reverses disease", "safe for everyone",
)


def enhanced_prompt_is_safe(original: str, enhanced: str) -> bool:
    original_low, enhanced_low = original.lower(), enhanced.lower()
    for phrase in _FORBIDDEN_ADDITIONS:
        if phrase in enhanced_low and phrase not in original_low:
            return False
    # Original must remain verbatim as the prefix; enhancement may clarify but cannot rewrite it.
    return enhanced.startswith(original.rstrip())


def manifest_path(project: Path) -> Path:
    return Path(project).resolve() / MANIFEST_NAME


def load_manifest(project: Path) -> dict[str, Any]:
    path = manifest_path(project)
    if not path.is_file():
        return {"version": 1, "images": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"version": 1, "images": {}}
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "images": {}}


def save_manifest(project: Path, data: dict[str, Any]) -> None:
    path = manifest_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def reconcile_manifest(project: Path, assignments: Iterable[ImageAssignment]) -> dict[str, Any]:
    data = load_manifest(project)
    images = data.setdefault("images", {})
    for a in assignments:
        rec = images.get(a.filename, {})
        if rec and rec.get("original_prompt_hash") and rec.get("original_prompt_hash") != a.original_prompt_hash and a.asset_path.is_file():
            rec["status"] = "STALE"
        elif a.asset_path.is_file() and not rec:
            rec = {"status": "EXISTING", "attempts": 0}
        elif not a.asset_path.is_file() and rec.get("status") in {"SUCCESS", "EXISTING", "STALE"}:
            rec["status"] = "PENDING"
        rec.update({
            "image_number": a.image_number, "filename": a.filename, "scene_id": a.scene_id,
            "image_prompt_id": a.image_prompt_id, "original_prompt_hash": a.original_prompt_hash,
            "output_path": str(a.asset_path),
        })
        images[a.filename] = rec
    data["version"] = 1
    data["project"] = Path(project).resolve().name
    data["updated_timestamp"] = datetime.now(timezone.utc).isoformat()
    save_manifest(project, data)
    return data


def validate_image(path: Path, expected: tuple[int, int], aspect_tolerance: float = 0.03) -> tuple[bool, str, tuple[int, int] | None]:
    if not path.is_file() or path.stat().st_size <= 0:
        return False, "output file is missing or empty", None
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            dims = image.size
            fmt = (image.format or "").upper()
    except Exception as exc:
        return False, f"invalid image: {type(exc).__name__}", None
    if fmt not in {"PNG", "JPEG", "WEBP"}:
        return False, f"unsupported image format: {fmt}", dims
    target_ratio = expected[0] / expected[1]
    ratio = dims[0] / max(1, dims[1])
    if abs(ratio - target_ratio) / target_ratio > aspect_tolerance:
        return False, f"unexpected aspect ratio {dims[0]}x{dims[1]}", dims
    return True, "", dims


def validate_model_dimensions(profile: ModelProfile) -> None:
    """Fail locally when a model profile contains dimensions invalid for that model.

    FLUX.1 Schnell (runware:100@1) requires each dimension to be 128..2048
    inclusive and divisible by 64. Other model profiles retain their existing
    provider-specific dimensions and behavior.
    """
    width, height = profile.dimensions
    if not isinstance(width, int) or isinstance(width, bool) or not isinstance(height, int) or isinstance(height, bool):
        raise ValueError(
            f"Invalid image dimensions for {profile.display_name}: {width}x{height}. "
            "Width and height must be integers."
        )
    if profile.model_id == "runware:100@1":
        invalid = (
            width < 128 or width > 2048 or height < 128 or height > 2048
            or width % 64 != 0 or height % 64 != 0
        )
        if invalid:
            raise ValueError(
                f"Invalid FLUX.1 Schnell dimensions: {width}x{height}. "
                "Runware requires width and height between 128 and 2048, in multiples of 64."
            )


def _runware_request(api_key: str, profile: ModelProfile, prompt: str, timeout: int = 120) -> tuple[bytes, float | None]:
    validate_model_dimensions(profile)
    width, height = profile.dimensions
    task: dict[str, Any] = {
        "taskType": "imageInference", "taskUUID": str(uuid.uuid4()), "model": profile.model_id,
        "positivePrompt": prompt, "width": width, "height": height, "outputType": "URL",
        "outputFormat": "PNG", "numberResults": 1, "deliveryMethod": "sync", "includeCost": True,
    }
    task.update(profile.defaults)
    body = json.dumps([task]).encode("utf-8")
    req = urllib.request.Request(RUNWARE_ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Runware HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TimeoutError(f"Runware network error: {exc.reason}") from exc
    if payload.get("errors") or payload.get("error"):
        raise RuntimeError(f"Runware rejected request: {str(payload.get('errors') or payload.get('error'))[:500]}")
    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError("Runware returned no image result")
    row = rows[0]
    image_url = row.get("imageURL")
    if not image_url:
        raise RuntimeError("Runware response did not contain imageURL")
    try:
        with urllib.request.urlopen(image_url, timeout=timeout) as response:
            content = response.read()
    except urllib.error.URLError as exc:
        raise TimeoutError(f"Runware image download failed: {exc.reason}") from exc
    return content, float(row["cost"]) if row.get("cost") is not None else None


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace(os.getenv("RUNWARE_API_KEY", ""), "***") if os.getenv("RUNWARE_API_KEY") else str(exc)
    return text[:600]


def generate_one(
    project: Path, assignment: ImageAssignment, profile: ModelProfile, enhancement_enabled: bool,
    retry_count: int = 2, timeout: int = 120,
    requester: Callable[[str, ModelProfile, str, int], tuple[bytes, float | None]] = _runware_request,
) -> GenerationResult:
    # Resolve project fresh and rebuild destination to prevent stale project paths.
    project = Path(project).resolve()
    destination = project / "assets" / "images" / assignment.filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    prompt = enhance_prompt(assignment.original_prompt, profile, enhancement_enabled)
    if not enhanced_prompt_is_safe(assignment.original_prompt, prompt):
        prompt = assignment.original_prompt
    try:
        validate_model_dimensions(profile)
    except ValueError as exc:
        return GenerationResult(assignment, "FAILED", 0, str(exc), enhanced_prompt=prompt)
    api_key = os.getenv("RUNWARE_API_KEY", "").strip()
    if not api_key and requester is _runware_request:
        return GenerationResult(assignment, "FAILED", 0, "RUNWARE_API_KEY is not configured", enhanced_prompt=prompt)
    started = time.monotonic()
    last_error = ""
    cost = None
    for attempt in range(1, max(0, retry_count) + 2):
        try:
            content, cost = requester(api_key, profile, prompt, timeout)
            destination.write_bytes(content)
            valid, error, dims = validate_image(destination, profile.dimensions)
            if not valid:
                destination.unlink(missing_ok=True)
                raise RuntimeError(error)
            return GenerationResult(assignment, "SUCCESS", attempt, elapsed_seconds=time.monotonic()-started, enhanced_prompt=prompt, dimensions=dims, cost=cost)
        except Exception as exc:
            last_error = _safe_error(exc)
            transient = isinstance(exc, (TimeoutError, urllib.error.URLError)) or any(x in last_error.lower() for x in ("timeout", "429", "500", "502", "503", "504", "network"))
            if attempt > retry_count or not transient:
                break
            time.sleep(min(2 ** (attempt - 1), 4))
    return GenerationResult(assignment, "FAILED", attempt, last_error, time.monotonic()-started, prompt, cost=cost)


def update_manifest_result(project: Path, result: GenerationResult, profile: ModelProfile) -> dict[str, Any]:
    project = Path(project).resolve()
    data = load_manifest(project)
    images = data.setdefault("images", {})
    a = result.assignment
    destination = project / "assets" / "images" / a.filename
    rec = images.get(a.filename, {})
    rec.update({
        "image_number": a.image_number, "filename": a.filename, "scene_id": a.scene_id,
        "image_prompt_id": a.image_prompt_id, "original_prompt_hash": a.original_prompt_hash,
        "enhanced_prompt_hash": sha256_text(result.enhanced_prompt or a.original_prompt),
        "selected_model": profile.display_name, "provider": profile.provider, "model_id": profile.model_id,
        "dimensions": list(result.dimensions or profile.dimensions), "output_path": str(destination),
        "status": result.status, "attempts": int(rec.get("attempts", 0)) + result.attempts,
        "generated_timestamp": datetime.now(timezone.utc).isoformat() if result.status == "SUCCESS" else rec.get("generated_timestamp"),
        "output_sha256": sha256_file(destination) if result.status == "SUCCESS" and destination.is_file() else "",
        "safe_error_summary": result.error, "last_elapsed_seconds": round(result.elapsed_seconds, 3),
    })
    if result.cost is not None:
        rec["reported_cost"] = result.cost
    images[a.filename] = rec
    data.update({"version": 1, "project": project.name, "updated_timestamp": datetime.now(timezone.utc).isoformat()})
    save_manifest(project, data)
    return data


def generate_batch(
    project: Path, assignments: list[ImageAssignment], profile: ModelProfile, enhancement_enabled: bool = True,
    retry_count: int = 2, max_workers: int = 3,
    requester: Callable[[str, ModelProfile, str, int], tuple[bytes, float | None]] = _runware_request,
    progress: Callable[[int, int, GenerationResult], None] | None = None,
) -> list[GenerationResult]:
    project = Path(project).resolve()
    results: list[GenerationResult] = []
    workers = max(1, min(int(max_workers), 8, len(assignments) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(generate_one, project, a, profile, enhancement_enabled, retry_count, 120, requester): a for a in assignments}
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            update_manifest_result(project, result, profile)
            results.append(result)
            if progress:
                progress(index, len(assignments), result)
    return sorted(results, key=lambda r: r.assignment.image_number)


def select_missing(assignments: list[ImageAssignment]) -> list[ImageAssignment]:
    return [a for a in assignments if not a.asset_path.is_file()]


def select_failed_or_missing(project: Path, assignments: list[ImageAssignment]) -> list[ImageAssignment]:
    manifest = load_manifest(project).get("images", {})
    return [a for a in assignments if not a.asset_path.is_file() or manifest.get(a.filename, {}).get("status") == "FAILED"]


def select_stale(project: Path, assignments: list[ImageAssignment]) -> list[ImageAssignment]:
    manifest = reconcile_manifest(project, assignments).get("images", {})
    return [a for a in assignments if manifest.get(a.filename, {}).get("status") == "STALE"]


def build_images_zip(project: Path, assignments: list[ImageAssignment]) -> bytes:
    project = Path(project).resolve()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for a in assignments:
            path = project / "assets" / "images" / a.filename
            if path.is_file():
                archive.write(path, arcname=a.filename)
    return buf.getvalue()
