# CapCut Desktop 8.7 AI-image motion structural validation

Authoritative reference: user-supplied manual CapCut Desktop 8.7 `draft_content.json`.

## Important reference note

The supplied reference file contains one animated image segment (Zoom In, 1.00 → 1.08). The Zoom Out export uses the same native lane/curve structure with reversed scale values and a mirrored signed Y control; no unrelated CapCut metadata is copied.

## Manual reference vs new exported image_001

| Animation field | Working manual CapCut | New export | Result |
|---|---|---|---|
| common_keyframes lane | `KFTypeScaleX` | `KFTypeScaleX` | MATCH |
| common_keyframes.material_id | `""` | `''` | MATCH |
| opening curveType | `FreeCurveInOut` | `FreeCurveInOut` | MATCH |
| opening time_offset | `0` | `0` | MATCH |
| opening value | `1.00` | `1.00` | MATCH |
| opening left_control | `{"x": 0.0, "y": 0.0}` | `{"x": 0.0, "y": 0.0}` | MATCH |
| opening right_control.x | `32% of segment duration` | `400000.0 (32%)` | MATCH |
| opening right_control.y | `94% of scale delta` | `0.075200 (94%)` | MATCH |
| ending curveType | `Line` | `Line` | MATCH |
| ending time_offset | `exact segment duration` | `1250000` | MATCH |
| ending value | `1.08` | `1.08` | MATCH |
| ending controls | `zero/zero` | `{"left": {"x": 0.0, "y": 0.0}, "right": {"x": 0.0, "y": 0.0}}` | MATCH |
| uniform_scale | `{"on": true, "value": 1.0}` | `{"on": true, "value": 1.0}` | MATCH |
| keyframe_refs | `[]` | `[]` | MATCH |
| clip.scale stored state | `ending scale 1.08` | `{"x": 1.08, "y": 1.08}` | MATCH |
| target/source duration relationship | `same duration` | `target=1250000, source=1250000` | MATCH |

## Four-image validation export

### image_001.png
- Motion: Zoom In
- Target duration: 1250000 µs
- Scale: 1.00 → 1.08
- Opening curve: FreeCurveInOut
- Opening right control: x=400000.0, y=0.07520000000000006
- End offset equals exact duration: True
- clip.scale equals final evaluated scale: {'x': 1.08, 'y': 1.08}

### image_002.png
- Motion: Zoom Out
- Target duration: 1250000 µs
- Scale: 1.08 → 1.00
- Opening curve: FreeCurveInOut
- Opening right control: x=400000.0, y=-0.07520000000000006
- End offset equals exact duration: True
- clip.scale equals final evaluated scale: {'x': 1.0, 'y': 1.0}

### image_003.png
- Motion: Zoom In
- Target duration: 1250000 µs
- Scale: 1.00 → 1.08
- Opening curve: FreeCurveInOut
- Opening right control: x=400000.0, y=0.07520000000000006
- End offset equals exact duration: True
- clip.scale equals final evaluated scale: {'x': 1.08, 'y': 1.08}

### image_004.png
- Motion: Zoom Out
- Target duration: 1250000 µs
- Scale: 1.08 → 1.00
- Opening curve: FreeCurveInOut
- Opening right control: x=400000.0, y=-0.07520000000000006
- End offset equals exact duration: True
- clip.scale equals final evaluated scale: {'x': 1.0, 'y': 1.0}
