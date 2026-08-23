import csv, json
from pathlib import Path
import pytest
from timeline_builder import TimelineBuildError, build_timeline_manifest


def make_project(tmp_path: Path, count=247):
    project=tmp_path/'Project'; project.mkdir()
    path=project/'08_actual_timeline.csv'
    with path.open('w',newline='',encoding='utf-8') as h:
        w=csv.DictWriter(h,fieldnames=['Scene ID','Script Text','Actual Audio Start','Actual Audio End','Duration','Avatar Chunk','Timing Source']); w.writeheader()
        for i in range(count):
            start=i*1.25; end=start+1.25
            w.writerow({'Scene ID':f'S{i+1:03d}','Script Text':f'Scene {i+1}','Actual Audio Start':f'{start:.3f}','Actual Audio End':f'{end:.3f}','Duration':'1.250','Avatar Chunk':'c1.mp4','Timing Source':'word'})
    total = count * 1.25
    (project / 'avatar_timing_manifest.json').write_text(json.dumps({
        'timeline_status': 'PASS',
        'total_avatar_duration': total,
        'chunks': [{
            'chunk_filename': 'c1.mp4',
            'global_audio_start': 0.0,
            'global_audio_end': total,
            'duration': total,
        }],
    }), encoding='utf-8')
    return project


def test_247_scenes_duration_and_placeholders(tmp_path):
    p=make_project(tmp_path)
    result=build_timeline_manifest(p)
    data=json.loads(result.manifest_path.read_text())
    assert result.scenes==247
    assert data['timeline']['duration_seconds']==pytest.approx(308.75)
    assert data['scenes'][0]['visual_assignment'] is None
    assert data['scenes'][-1]['visual_assignment'] is None
    assert data['base_avatar']['chunks'][0]['reference'] == 'avatars/c1.mp4'
    assert data['scenes'][10]['timing']['start_seconds']==12.5


def test_repeated_build_is_identical(tmp_path):
    p=make_project(tmp_path,3)
    a=build_timeline_manifest(p).manifest_path.read_bytes()
    b=build_timeline_manifest(p).manifest_path.read_bytes()
    assert a==b


def test_rejects_missing_avatar_and_bad_duration(tmp_path):
    p=make_project(tmp_path,1); path=p/'08_actual_timeline.csv'
    text=path.read_text().replace('c1.mp4','').replace('1.250','-1.250')
    path.write_text(text)
    with pytest.raises(TimelineBuildError): build_timeline_manifest(p)

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("00:00", 0.0),
        ("00:00.0", 0.0),
        ("00:04.8", 4.8),
        ("01:02.3", 62.3),
        ("00:01:02", 62.0),
        ("00:01:02.250", 62.25),
        ("01:10:00.000", 4200.0),
        ("12.4", 12.4),
        ("300", 300.0),
        ("  00:04.800  ", 4.8),
        (12.4, 12.4),
        (300, 300.0),
    ],
)
def test_parse_timeline_time_supported_formats(value, expected):
    from timeline_builder import parse_timeline_time

    assert parse_timeline_time(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["", "abc", "1:2:3:4", "00::04", "00:60", "00:01:60", "1m:02s"])
def test_parse_timeline_time_rejects_malformed(value):
    from timeline_builder import parse_timeline_time

    with pytest.raises(ValueError, match="timeline time|empty"):
        parse_timeline_time(value)


@pytest.mark.parametrize("value", [-1, -0.1, "-1", "-0.1"])
def test_parse_timeline_time_rejects_negative(value):
    from timeline_builder import parse_timeline_time

    with pytest.raises(ValueError, match="negative"):
        parse_timeline_time(value)


def test_real_first_five_rows_parse_with_rounded_duration_tolerance(tmp_path):
    project = tmp_path / "RealRows"
    project.mkdir()
    path = project / "08_actual_timeline.csv"
    rows = [
        ("S001", "00:00.0", "00:04.5", "4.48"),
        ("S002", "00:04.8", "00:09.1", "4.3"),
        ("S003", "00:09.1", "00:13.7", "4.56"),
        ("S004", "00:13.7", "00:18.5", "4.78"),
        ("S005", "00:18.5", "00:24.2", "5.68"),
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "Scene ID", "Script Text", "Actual Audio Start", "Actual Audio End",
            "Duration", "Avatar Chunk", "Timing Source",
        ])
        writer.writeheader()
        for scene_id, start, end, duration in rows:
            writer.writerow({
                "Scene ID": scene_id,
                "Script Text": scene_id,
                "Actual Audio Start": start,
                "Actual Audio End": end,
                "Duration": duration,
                "Avatar Chunk": "c1.mp4",
                "Timing Source": "word",
            })

    result = build_timeline_manifest(project)
    data = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.scenes == 5
    assert data["timeline"]["duration_seconds"] == pytest.approx(24.2)
    assert [scene["timing"]["start_seconds"] for scene in data["scenes"]] == pytest.approx([0.0, 4.8, 9.1, 13.7, 18.5])
    assert [scene["timing"]["duration_seconds"] for scene in data["scenes"]] == pytest.approx([4.5, 4.3, 4.6, 4.8, 5.7])
    assert [scene["timing"]["reported_duration_seconds"] for scene in data["scenes"]] == pytest.approx([4.48, 4.3, 4.56, 4.78, 5.68])


def test_duration_difference_beyond_tolerance_fails_with_row_and_column(tmp_path):
    project = make_project(tmp_path, 1)
    path = project / "08_actual_timeline.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    rows[0]["Duration"] = "1.500"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(TimelineBuildError, match=r"Row 1: Duration differs.*tolerance 0\.150s"):
        build_timeline_manifest(project)


def test_malformed_start_reports_row_and_column(tmp_path):
    project = make_project(tmp_path, 1)
    path = project / "08_actual_timeline.csv"
    text = path.read_text(encoding="utf-8").replace("0.000", "00::00", 1)
    path.write_text(text, encoding="utf-8")

    with pytest.raises(TimelineBuildError, match=r"Row 1: invalid Actual Audio Start"):
        build_timeline_manifest(project)


def test_production_sheet_assignments_only_create_real_visual_slots(tmp_path):
    p = make_project(tmp_path, 5)
    fields = ['scene_id','recommended_asset_type','image_prompt_id','broll_prompt_id','selected_asset_path']
    with (p/'07_production_sheet.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        writer.writerow({'scene_id':'S001','recommended_asset_type':'AI_IMAGE','image_prompt_id':'IMG-001'})
        writer.writerow({'scene_id':'S002','recommended_asset_type':'AVATAR'})
        writer.writerow({'scene_id':'S003','recommended_asset_type':'STOCK_VIDEO','broll_prompt_id':'BR-001'})
        writer.writerow({'scene_id':'S004','recommended_asset_type':'OVERLAY'})
        writer.writerow({'scene_id':'S005','recommended_asset_type':'AI_IMAGE','image_prompt_id':'IMG-002'})
    data = json.loads(build_timeline_manifest(p).manifest_path.read_text())
    assert data['production_assignments']['image_count'] == 2
    assert data['production_assignments']['broll_count'] == 1
    assert data['scenes'][0]['visual_assignment']['reference'] == 'assets/images/image_001.png'
    assert data['scenes'][2]['visual_assignment']['reference'] == 'assets/broll/broll_001.mp4'
    assert data['scenes'][4]['visual_assignment']['reference'] == 'assets/images/image_002.png'
    assert data['scenes'][1]['visual_assignment'] is None

def test_stock_image_is_loaded_as_broll_assignment(tmp_path):
    import csv
    project = tmp_path / "Project"
    (project / "assets" / "broll").mkdir(parents=True)
    (project / "assets" / "broll" / "BR001.jpg").write_bytes(b"fake-jpg")
    with (project / "07_production_sheet.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene_id","recommended_asset_type","image_prompt_id","broll_prompt_id","selected_asset_path"])
        writer.writeheader()
        writer.writerow({"scene_id":"S001","recommended_asset_type":"STOCK_IMAGE","broll_prompt_id":"BR001"})
    from timeline_builder import _load_production_assignments
    assignments = _load_production_assignments(project)
    assert assignments["S001"]["kind"] == "broll"
    assert assignments["S001"]["production_asset_type"] == "STOCK_IMAGE"
    assert assignments["S001"]["reference"] == "assets/broll/BR001.jpg"
