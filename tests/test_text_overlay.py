import csv, json
from pathlib import Path
import pytest
from text_overlay import *


def fixture_project(tmp_path: Path):
    p=tmp_path/'A'; p.mkdir(parents=True); (p/'avatar_transcripts').mkdir()
    rows=[
      ('S001','A level tablespoon can be a small, reasonable food choice, roughly ninety-five calories.','00:00.000','00:05.000'),
      ('S002','A heaping one can quietly change your whole calorie story without you noticing.','00:05.000','00:10.000'),
      ('S003','There is no proven bedtime benefit in the evidence discussed here.','00:10.000','00:15.000')]
    with (p/'08_actual_timeline.csv').open('w',encoding='utf-8',newline='') as h:
      f=['Scene ID','Script Text','Actual Audio Start','Actual Audio End','Duration','Avatar Chunk','Timing Source']; w=csv.DictWriter(h,fieldnames=f); w.writeheader()
      for sid,text,s,e in rows:w.writerow({'Scene ID':sid,'Script Text':text,'Actual Audio Start':s,'Actual Audio End':e,'Duration':'5','Avatar Chunk':'c1.mp4','Timing Source':'word'})
    alltext=' '.join(r[1] for r in rows); toks=normalize_anchor(alltext).split(); words=[]
    for i,t in enumerate(toks): words.append({'word':t,'start':i*0.5,'end':(i+1)*0.5})
    (p/'avatar_transcripts'/'c1.json').write_text(json.dumps({'duration':len(toks)*0.5,'text':alltext,'words':words}),encoding='utf-8')
    return p

def row(n=1, text='LEVEL SPOON | ≈ 95 CALORIES', typ='NUMBER'):
 return {'Overlay Number':str(n),'Script Line Start':'A level tablespoon can be a small, reasonable food choice, roughly ninety-five calories.','Script Line End':'A heaping one can quietly change your whole calorie story without you noticing.','Overlay Text':text,'Overlay Type':typ}

def test_parse_and_types_and_word_timing(tmp_path):
 p=fixture_project(tmp_path); r=validate_rows(p,[row()]); assert r.passed; x=r.records[0]; assert x.overlay_number==1 and x.timing_source=='word_timestamps' and x.start_seconds==0 and x.end_seconds>0

def test_unicode_punctuation_and_pipe():
 assert normalize_anchor('“Hello”—world')==normalize_anchor('Hello - world'); assert clean_text('â‰ˆ Â· â€“')=='≈ · –'; assert visual_text('MEASURE FIRST | THEN OBSERVE')=='MEASURE FIRST\nTHEN OBSERVE'

def test_wrong_anchor_rejected(tmp_path):
 p=fixture_project(tmp_path); q=row();q['Script Line Start']='Genuinely different sentence';r=validate_rows(p,[q]);assert not r.passed and r.records[0].status=='MISMATCH'

def test_unknown_type_fails(tmp_path):
 p=fixture_project(tmp_path); assert not validate_rows(p,[row(typ='OTHER')]).passed

def test_no_opus_timing_columns_used(tmp_path):
 p=fixture_project(tmp_path); q=row();q['Start']='999';q['End']='1000';x=validate_rows(p,[q]).records[0];assert x.start_seconds!=999 and x.end_seconds!=1000

def test_artifact_and_project_isolation(tmp_path):
 a=fixture_project(tmp_path); b=fixture_project(tmp_path/'other'); r=validate_rows(a,[row()]); path=write_artifact(a,r); assert path.name=='11_text_overlays.csv' and not (b/'11_text_overlays.csv').exists(); data=load_artifact(path);assert data[0]['overlay_id']=='OVL001'

def test_overlap_rejected(tmp_path):
 p=fixture_project(tmp_path); r=validate_rows(p,[row(1),row(2,'SECOND','ACTION')]); assert not r.passed and any('overlap' in e.lower() for e in r.errors)


def _write_evidence_sources(p: Path, research: str, medical: str):
    (p/'02_research_sheet.md').write_text(research, encoding='utf-8')
    (p/'13_fact_check_log.md').write_text(medical, encoding='utf-8')


def test_legacy_artifact_loads_as_standard(tmp_path):
    p=tmp_path/'legacy.csv'
    p.write_text('overlay_id,overlay_number,start_seconds,end_seconds,duration_seconds,overlay_text,overlay_type,script_line_start,script_line_end,timing_source,status,priority\nOVL001,1,0,2,2,FACT,KEY FACT,a,b,word_timestamps,READY,100\n',encoding='utf-8')
    assert load_artifact(p)[0]['overlay_class']=='STANDARD'


def test_valid_evidence_and_generic_research_drop(tmp_path):
    from evidence_overlay import analyze_project_evidence
    p=fixture_project(tmp_path)
    # Replace timeline with a specific study scene plus generic research scene.
    with (p/'08_actual_timeline.csv').open('w',encoding='utf-8',newline='') as h:
        f=['Scene ID','Script Text','Actual Audio Start','Actual Audio End']; w=csv.DictWriter(h,fieldnames=f);w.writeheader()
        w.writerow({'Scene ID':'S001','Script Text':'A 2019 study followed 120 older adults and found walking was associated with 20% lower risk.','Actual Audio Start':'00:00','Actual Audio End':'00:06'})
        w.writerow({'Scene ID':'S002','Script Text':'Research suggests exercise may help.','Actual Audio Start':'00:06','Actual Audio End':'00:10'})
    _write_evidence_sources(p,
      'A 2019 study included 120 older adults. The cohort was followed for 12 months. Walking was associated with 20% lower risk.',
      'Approved framing: walking was associated with 20% lower risk; do not claim it caused the reduction.')
    rows=load_actual_timeline(p/'08_actual_timeline.csv'); ev,diag=analyze_project_evidence(p,rows)
    assert len(ev)==1 and len(ev[0].bullets)==3 and '2019' in ev[0].heading
    assert all('Research suggests exercise may help' not in e.script_text for e in ev)


def test_missing_year_and_author_are_not_invented(tmp_path):
    from evidence_overlay import analyze_project_evidence
    p=fixture_project(tmp_path)
    with (p/'08_actual_timeline.csv').open('w',encoding='utf-8',newline='') as h:
        f=['Scene ID','Script Text','Actual Audio Start','Actual Audio End'];w=csv.DictWriter(h,fieldnames=f);w.writeheader();w.writerow({'Scene ID':'S1','Script Text':'A study of 120 older adults found walking was linked to lower risk.','Actual Audio Start':'0','Actual Audio End':'5'})
    _write_evidence_sources(p,'A study included 120 older adults. Participants were observed during daily walking. Walking was linked to lower risk.','Walking was linked to lower risk; causation is not established.')
    ev,_=analyze_project_evidence(p,load_actual_timeline(p/'08_actual_timeline.csv'))
    assert ev and '2019' not in ev[0].heading and 'BMJ' not in ' '.join(ev[0].bullets)


def test_standard_evidence_collision_shift_and_drop():
    ev=OverlayRecord('EVD002',2,4,6,2,'','KEY FACT','e','e','actual','READY',300,overlay_class='EVIDENCE',heading='STUDY',bullet_1='a',bullet_2='b',bullet_3='c',source_trace='{"source_matches":["x"],"medical_matches":["y"]}',claim_key='k',allowed_start_seconds=4,allowed_end_seconds=6)
    st=OverlayRecord('OVL001',1,4.5,5.5,1,'FACT','KEY FACT','a','b','word','READY',100,allowed_start_seconds=2,allowed_end_seconds=8)
    rows,errs,warns=schedule_unified_overlays([st],[ev],0.25)
    assert not errs and any(r.overlay_id=='OVL001' and r.start_seconds < 4 for r in rows)
    st2=OverlayRecord('OVL003',3,4.5,5.5,1,'FACT','KEY FACT','a','b','word','READY',100,allowed_start_seconds=4.4,allowed_end_seconds=5.6)
    rows,errs,warns=schedule_unified_overlays([st2],[ev],0.25)
    assert not any(r.overlay_id=='OVL003' for r in rows) and st2.diagnostic=='STANDARD_DROPPED_FOR_EVIDENCE_COLLISION'


def test_evidence_collision_deterministic_and_three_bullets_required():
    from evidence_overlay import EvidenceCandidate
    a=OverlayRecord('EVD001',1,0,5,5,'','KEY FACT','','','actual','READY',300,overlay_class='EVIDENCE',heading='H',bullet_1='1',bullet_2='2',bullet_3='3',source_trace='{"source_matches":["x"],"medical_matches":["y"]}',claim_key='a')
    b=OverlayRecord('EVD002',2,1,4,3,'','KEY FACT','','','actual','READY',300,overlay_class='EVIDENCE',heading='H',bullet_1='1',bullet_2='2',bullet_3='3',source_trace='{}',claim_key='b')
    rows,errs,_=schedule_unified_overlays([], [a,b], 0)
    assert not errs and [r.overlay_id for r in rows]==['EVD001']
    assert len(EvidenceCandidate('s','x',0,1,'h',['1','2','3'],'{}','k','x','x').bullets)==3

def test_local_word_anchor_resolver_recovers_asr_endpoint_mismatch(tmp_path):
    p=fixture_project(tmp_path)
    # Corrupt one transcript token at the beginning of the first anchor so the
    # global timeline->word mapping cannot map that endpoint exactly.
    tp=p/'avatar_transcripts'/'c1.json'
    payload=json.loads(tp.read_text(encoding='utf-8'))
    payload['words'][0]['word']='levelx'
    tp.write_text(json.dumps(payload),encoding='utf-8')
    r=validate_rows(p,[row()])
    assert r.passed
    rec=r.records[0]
    assert rec.timing_source in {'word_timestamps_local_fuzzy','word_timestamps_local_exact','word_timestamps'}
    assert rec.timing_source != 'actual_timeline_boundary_fallback'
