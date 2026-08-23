from __future__ import annotations

import csv
import re
from pathlib import Path

PRODUCTION_SHEET_COLUMNS = [
    "scene_id","start_time","end_time","duration_sec","scene_purpose","script_excerpt",
    "visual_mode","avatar_required","avatar_style","background_style","image_prompt_id","broll_prompt_id",
    "narrative_context","visual_intent","filmable","asset_decision_reason","asset_search_query",
    "alternative_search_query_1","alternative_search_query_2","ai_image_prompt","overlay_instruction",
    "recommended_asset_type","recommended_shot","manual_search_notes","avoid_results","asset_source",
    "selected_asset_path","asset_status","motion","transition","on_screen_text","notes",
]

ASSET_STATUS = {
    "STOCK_VIDEO": "TO_FIND", "STOCK_IMAGE": "TO_FIND", "AI_IMAGE": "GENERATE",
    "AVATAR": "READY", "OVERLAY": "DESIGN", "SPLIT_SCREEN": "TO_ASSEMBLE",
    "NO_ASSET_NEEDED": "NOT_NEEDED",
}
_ALLOWED_ASSETS=set(ASSET_STATUS)


def _clean(v: object) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _asset(raw: str) -> str:
    value=_clean(raw).upper()
    aliases={"STOCK":"STOCK_VIDEO","BROLL":"STOCK_VIDEO","IMAGE":"AI_IMAGE","AI":"AI_IMAGE",
             "TEXT_OVERLAY":"OVERLAY","STANDARD_TEXT_OVERLAY":"OVERLAY","EVIDENCE_OVERLAY":"OVERLAY"}
    value=aliases.get(value,value)
    return value if value in _ALLOWED_ASSETS else "AVATAR"


def _visual_mode(asset: str) -> str:
    return {"AVATAR":"avatar_only","AI_IMAGE":"fullscreen_image","STOCK_VIDEO":"broll",
            "STOCK_IMAGE":"fullscreen_image","OVERLAY":"avatar_with_overlay","SPLIT_SCREEN":"split_screen",
            "NO_ASSET_NEEDED":"avatar_only"}[asset]


def _purpose(raw: str) -> str:
    v=_clean(raw).upper()
    aliases={"CONTENT":"EXPLAIN","STRUCTURAL":"CREDIBILITY","STRUCTURAL_CLOSE":"RECAP","CLOSE":"RECAP","INTRO":"HOOK"}
    v=aliases.get(v,v)
    allowed={"HOOK","PROBLEM","CREDIBILITY","MECHANISM","PROOF","SOLUTION","WARNING","RECAP","CTA","EXPLAIN"}
    return v if v in allowed else "EXPLAIN"


def _duration(start: str, end: str, raw: str) -> str:
    if _clean(raw):
        try: return f"{float(raw):.2f}"
        except ValueError: return _clean(raw)
    def sec(x:str):
        x=x.strip(); parts=x.split(':')
        try:
            if len(parts)==2: return float(parts[0])*60+float(parts[1])
            if len(parts)==3: return float(parts[0])*3600+float(parts[1])*60+float(parts[2])
        except ValueError: pass
        return None
    a,b=sec(start),sec(end)
    return f"{max(0.01,b-a):.2f}" if a is not None and b is not None else ""




def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", _clean(text)))


def _time_is_mmss(value: str) -> bool:
    # Production timing is provisional and must stay elapsed M:SS, never time-of-day HH:MM:SS.
    return bool(re.fullmatch(r"\d{1,4}:[0-5]\d(?:\.\d+)?", _clean(value)))


def _duration_seconds(raw: str) -> float | None:
    try:
        return float(_clean(raw))
    except (TypeError, ValueError):
        return None


def validate_scene_segmentation(rows: list[dict[str, str]]) -> list[str]:
    """Validate semantic scene sizing before downstream asset/timeline work.

    Scene boundaries are narration/visual-idea boundaries, not fixed-duration or mix quotas.
    Tiny fragments must normally be merged; overly broad excerpts must be split.
    """
    issues: list[str] = []
    for idx, row in enumerate(rows, 1):
        sid = _clean(row.get("scene_id")) or f"row {idx}"
        excerpt = _clean(row.get("script_excerpt"))
        words = _word_count(excerpt)
        notes = _clean(row.get("notes")).upper()
        intentional = "INTENTIONAL_EMPHASIS" in notes
        intentional_long_avatar = ("INTENTIONAL_LONG_AVATAR" in notes and _clean(row.get("recommended_asset_type")).upper() == "AVATAR")

        if 0 < words < 4 and not intentional:
            issues.append(
                f"{sid}: script_excerpt has only {words} words; merge this tiny fragment with an adjacent semantic beat "
                "unless it is deliberately marked INTENTIONAL_EMPHASIS in notes."
            )
        if words > 32 and not intentional_long_avatar:
            issues.append(
                f"{sid}: script_excerpt has {words} words; split it at a natural visual/semantic idea change (target roughly 10-24 words; 25-32 is allowed only for one coherent visual idea)."
            )

        start = _clean(row.get("start_time"))
        end = _clean(row.get("end_time"))
        if start and not _time_is_mmss(start):
            issues.append(f"{sid}: start_time must use elapsed M:SS format, got {start!r}.")
        if end and not _time_is_mmss(end):
            issues.append(f"{sid}: end_time must use elapsed M:SS format, got {end!r}.")

        duration = _duration_seconds(row.get("duration_sec"))
        if duration is not None and words:
            # A generous ceiling catches quota-driven timings such as 6 sec for "Just five."
            # while allowing slower senior-health narration and meaningful pauses.
            plausible_max = max(3.0, (words / 105.0) * 60.0 + 1.0)
            if duration > plausible_max + 0.05:
                issues.append(
                    f"{sid}: duration_sec={duration:g} is too long for a {words}-word excerpt; derive provisional timing from narration length, "
                    "not a fixed scene-duration bucket."
                )
    return issues

def validate_canonical_rows(rows: list[dict[str,str]], fieldnames: list[str] | None, *, check_segmentation: bool = True) -> list[str]:
    issues=[]
    if fieldnames != PRODUCTION_SHEET_COLUMNS:
        issues.append("07_production_sheet.csv header does not match the canonical 32-column Production schema.")
    if not rows:
        issues.append("07_production_sheet.csv has no production scenes.")
        return issues
    seen=set(); img_ids=[]; br_ids=[]
    for idx,row in enumerate(rows,1):
        sid=_clean(row.get("scene_id"))
        if not re.fullmatch(r"S\d{3,}", sid): issues.append(f"row {idx}: invalid scene_id {sid!r}")
        if sid in seen: issues.append(f"row {idx}: duplicate scene_id {sid}")
        seen.add(sid)
        asset=_clean(row.get("recommended_asset_type")).upper()
        if asset not in _ALLOWED_ASSETS: issues.append(f"{sid}: invalid recommended_asset_type {asset!r}")
        expected=ASSET_STATUS.get(asset)
        if expected and _clean(row.get("asset_status")) != expected: issues.append(f"{sid}: asset_status must be {expected} for {asset}")
        for c in ("script_excerpt","narrative_context","visual_intent","asset_decision_reason"):
            if not _clean(row.get(c)): issues.append(f"{sid}: {c} is empty")
        if asset=="AI_IMAGE":
            pid=_clean(row.get("image_prompt_id")); img_ids.append(pid)
            if not pid: issues.append(f"{sid}: AI_IMAGE requires image_prompt_id")
            if not _clean(row.get("ai_image_prompt")): issues.append(f"{sid}: AI_IMAGE requires ai_image_prompt")
        elif _clean(row.get("image_prompt_id")):
            issues.append(f"{sid}: non-AI_IMAGE row must not carry image_prompt_id")
        if asset in {"STOCK_VIDEO","STOCK_IMAGE"}:
            bid=_clean(row.get("broll_prompt_id")); br_ids.append(bid)
            if not bid: issues.append(f"{sid}: stock row requires broll_prompt_id")
            for c in ("asset_search_query","alternative_search_query_1","alternative_search_query_2","manual_search_notes","avoid_results"):
                if not _clean(row.get(c)): issues.append(f"{sid}: stock row requires {c}")
    if check_segmentation:
        issues.extend(validate_scene_segmentation(rows))
    if img_ids and img_ids != [f"IMG{i:03d}" for i in range(1,len(img_ids)+1)]:
        issues.append("AI_IMAGE image_prompt_id values must be sequential IMG001..IMGNNN in Production assignment order.")
    if br_ids and br_ids != [f"BR{i:03d}" for i in range(1,len(br_ids)+1)]:
        issues.append("Stock broll_prompt_id values must be sequential BR001..BRNNN in Production assignment order.")
    return issues


def normalize_production_sheet(path: Path) -> tuple[bool,list[str]]:
    """Normalize legacy/compact Production output into the canonical 32-column contract.

    The rich canonical schema is preferred at generation time. This is a deterministic compatibility
    fallback so downstream Opus image import, image generation, avatar timing, timeline and CapCut all
    see the same interface even if an external LLM emits the older compact schema.
    """
    path=Path(path)
    with path.open(encoding="utf-8-sig",newline="") as h:
        reader=csv.DictReader(h); rows=list(reader); fields=list(reader.fieldnames or [])
    if fields == PRODUCTION_SHEET_COLUMNS:
        issues=validate_canonical_rows(rows,fields)
        return not issues, issues
    if not rows:
        return False,["07_production_sheet.csv has no rows to normalize."]

    out=[]; image_no=0; broll_no=0
    for idx,r in enumerate(rows,1):
        sid=_clean(r.get("scene_id") or r.get("slot_id"))
        if not re.fullmatch(r"S\d{3,}",sid): sid=f"S{idx:03d}"
        asset=_asset(r.get("recommended_asset_type") or r.get("asset_type") or r.get("slot_type") or r.get("visual_type"))
        excerpt=_clean(r.get("script_excerpt") or r.get("script_context_or_visual_direction") or r.get("narration") or r.get("Script Text"))
        context=_clean(r.get("narrative_context")) or f"Current narration: {excerpt}"
        intent=_clean(r.get("visual_intent")) or f"Illustrate the exact narration beat clearly and literally without adding a new medical claim: {excerpt[:180]}"
        start=_clean(r.get("start_time")); end=_clean(r.get("end_time"))
        if asset=="AI_IMAGE": image_no+=1
        if asset in {"STOCK_VIDEO","STOCK_IMAGE"}: broll_no+=1
        image_id=f"IMG{image_no:03d}" if asset=="AI_IMAGE" else ""
        broll_id=f"BR{broll_no:03d}" if asset in {"STOCK_VIDEO","STOCK_IMAGE"} else ""
        filmable="YES" if asset in {"STOCK_VIDEO","STOCK_IMAGE"} else ("NO" if asset=="AI_IMAGE" else "PARTIAL")
        if asset=="AVATAR": reason="Trust-building, explanation, transition, recap, or caution is best handled by the educational presenter."
        elif asset=="AI_IMAGE": reason="The scene needs a controlled illustrative visual matched to the exact narration and is not reliably represented by generic stock footage."
        elif asset in {"STOCK_VIDEO","STOCK_IMAGE"}: reason="The narration describes a concrete real-world subject or action that can be shown naturally with stock footage."
        elif asset=="OVERLAY": reason="The base presenter/footage can carry the scene; concise on-screen emphasis improves comprehension without requiring a new full-screen asset."
        else: reason="This asset lane best communicates the exact narration without changing its meaning."
        concrete=_clean(r.get("asset_search_query")) or intent
        # fallback queries stay concrete-ish and are only used for stock rows
        q1=_clean(r.get("alternative_search_query_1")) or (f"older adult {intent}" if asset in {"STOCK_VIDEO","STOCK_IMAGE"} else "")
        q2=_clean(r.get("alternative_search_query_2")) or (f"close up {intent}" if asset in {"STOCK_VIDEO","STOCK_IMAGE"} else "")
        if asset not in {"STOCK_VIDEO","STOCK_IMAGE"}: concrete=q1=q2=""
        ai=_clean(r.get("ai_image_prompt"))
        if asset=="AI_IMAGE" and not ai:
            ai=("Photorealistic senior-health documentary image, 16:9. " + intent + ". "
                "Match the exact narration context; realistic human proportions and natural lighting; no readable text, logos, fake medical charts, disease transformation, miracle imagery, or unsupported before/after claims.")
        overlay=_clean(r.get("overlay_instruction"))
        if asset=="OVERLAY" and not overlay: overlay="Use one concise mobile-readable text/graphic emphasis derived only from the current narration; add no new factual or medical claim."
        shot=_clean(r.get("recommended_shot")) or ({"AVATAR":"medium presenter shot","AI_IMAGE":"medium documentary composition","STOCK_VIDEO":"medium documentary action shot","STOCK_IMAGE":"documentary still","OVERLAY":"presenter or footage with clean overlay space"}.get(asset,"context-appropriate shot"))
        manual=_clean(r.get("manual_search_notes"))
        avoid=_clean(r.get("avoid_results"))
        if asset in {"STOCK_VIDEO","STOCK_IMAGE"}:
            manual=manual or "Find natural age-appropriate footage that matches the exact subject/action and setting in this narration; prefer realistic everyday behavior and no visible brands."
            avoid=avoid or "Avoid unrelated exercise, fake clinicians, sensational illness imagery, logos, readable brands, miracle-health visuals, and footage that contradicts the narration."
        source={"AVATAR":"AVATAR","AI_IMAGE":"AI_GENERATED","STOCK_VIDEO":"STOCK_SEARCH","STOCK_IMAGE":"STOCK_SEARCH","OVERLAY":"OVERLAY","SPLIT_SCREEN":"ASSEMBLY","NO_ASSET_NEEDED":"NONE"}[asset]
        selected=f"assets/images/image_{image_no:03d}.png" if asset=="AI_IMAGE" else ""
        motion={"AVATAR":"subtle presenter framing","AI_IMAGE":"slow push-in","STOCK_VIDEO":"natural b-roll motion","STOCK_IMAGE":"slow push-in","OVERLAY":"subtle overlay animation"}.get(asset,"none")
        out.append({
            "scene_id":sid,"start_time":start,"end_time":end,"duration_sec":_duration(start,end,r.get("duration_sec") or r.get("duration_seconds")),
            "scene_purpose":_purpose(r.get("scene_purpose") or r.get("discourse_role")),"script_excerpt":excerpt,
            "visual_mode":_clean(r.get("visual_mode")) or _visual_mode(asset),"avatar_required":"YES" if asset=="AVATAR" else "NO",
            "avatar_style":_clean(r.get("avatar_style")) or ("virtual_educational_presenter" if asset=="AVATAR" else ""),
            "background_style":_clean(r.get("background_style")) or ("warm neutral educational studio" if asset=="AVATAR" else ""),
            "image_prompt_id":image_id,"broll_prompt_id":broll_id,"narrative_context":context,"visual_intent":intent,"filmable":filmable,
            "asset_decision_reason":reason,"asset_search_query":concrete,"alternative_search_query_1":q1,"alternative_search_query_2":q2,
            "ai_image_prompt":ai,"overlay_instruction":overlay,"recommended_asset_type":asset,"recommended_shot":shot,
            "manual_search_notes":manual,"avoid_results":avoid,"asset_source":source,"selected_asset_path":selected,
            "asset_status":ASSET_STATUS[asset],"motion":motion,"transition":_clean(r.get("transition")) or "soft cut",
            "on_screen_text":_clean(r.get("on_screen_text")),"notes":_clean(r.get("notes")) or "Production timing is provisional until 08_actual_timeline.csv exists.",
        })
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8-sig',newline='') as h:
        w=csv.DictWriter(h,fieldnames=PRODUCTION_SHEET_COLUMNS,extrasaction='ignore'); w.writeheader(); w.writerows(out)
    tmp.replace(path)
    issues=validate_canonical_rows(out,PRODUCTION_SHEET_COLUMNS, check_segmentation=False)
    return not issues,issues
