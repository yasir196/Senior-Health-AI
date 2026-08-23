import csv
from pathlib import Path
import pytest
from seo_chapters import SEOChapterError, finalize_chapters

FIELDS=["Scene ID","Script Text","Actual Audio Start","Actual Audio End","Duration","Avatar Chunk","Timing Source"]
def timeline(tmp_path, rows):
    p=tmp_path/'08_actual_timeline.csv'
    with p.open('w',encoding='utf-8',newline='') as h:
        w=csv.DictWriter(h,fieldnames=FIELDS); w.writeheader()
        for scene,start in rows:
            w.writerow({"Scene ID":scene,"Script Text":scene,"Actual Audio Start":start,"Actual Audio End":"99:59","Duration":"1","Avatar Chunk":"c1","Timing Source":"aligned"})
    return p

def doc(body, other='UNCHANGED'):
    return f"## 1. Title\n{other}\n\n## 5. Chapters / Timestamps\n\n{body}\n\n## 6. Tags\n{other}\n"

def test_normal_fractional_fake_timestamp_and_other_sections_unchanged(tmp_path):
    p=timeline(tmp_path,[("S001","0"),("S010","01:05.9"),("S020","06:18.9")])
    out,diag=finalize_chapters(doc("09:59 S001 | Intro\n88:88 S010 | First Topic\nS020 | Second Topic"),p)
    assert "00:00 Intro" in out and "01:05 First Topic" in out and "06:18 Second Topic" in out
    assert "09:59" not in out and "88:88" not in out and out.count("UNCHANGED")==2 and not diag

def test_over_one_hour(tmp_path):
    p=timeline(tmp_path,[("S001",0),("S002","1:02:15.8")])
    out,_=finalize_chapters(doc("S001 | Intro\nS002 | Long Topic"),p)
    assert "1:02:15 Long Topic" in out

def test_missing_timeline_hard_fails(tmp_path):
    with pytest.raises(SEOChapterError,match="Actual Timeline required"):
        finalize_chapters(doc("S001 | Intro"),tmp_path/'missing.csv')

def test_missing_scene_drops_without_guess(tmp_path):
    p=timeline(tmp_path,[("S001",0),("S003",30)])
    out,diag=finalize_chapters(doc("S001 | Intro\nS002 | Missing\nS003 | End"),p)
    assert "Missing" not in out and any("S002" in d for d in diag)

def test_duplicate_second_and_nonmonotonic_are_dropped(tmp_path):
    p=timeline(tmp_path,[("S001",0),("S002",10.1),("S003",10.9),("S004",9.0),("S005",20)])
    out,diag=finalize_chapters(doc("S001 | Intro\nS002 | A\nS003 | B\nS004 | C\nS005 | D"),p)
    assert "00:10 A\n" in out and "00:10 B" not in out and "00:09 C" not in out and "00:20 D" in out and len(diag)==2

def test_actual_timeline_change_changes_regenerated_output(tmp_path):
    p=timeline(tmp_path,[("S001",0),("S002",12)])
    source=doc("S001 | Intro\nS002 | Topic")
    out,_=finalize_chapters(source,p); assert "00:12 Topic" in out
    p=timeline(tmp_path,[("S001",0),("S002",27)])
    out,_=finalize_chapters(source,p); assert "00:27 Topic" in out

def test_existing_time_formats_numeric_mmss_hhmmss(tmp_path):
    p=timeline(tmp_path,[("S001",0.0),("S002","02:03.4"),("S003","1:00:00.2")])
    out,_=finalize_chapters(doc("S001 | Intro\nS002 | Mid\nS003 | Hour"),p)
    assert "02:03 Mid" in out and "1:00:00 Hour" in out
