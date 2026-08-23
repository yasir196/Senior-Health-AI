from __future__ import annotations

import hashlib
import json
import os
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from image_generation import (
    DEFAULT_MODEL_KEY, MODEL_PROFILES, ModelProfile, _runware_request, build_images_zip,
    enhance_prompt, generate_batch, load_manifest, load_production_image_assignments,
    reconcile_manifest, select_missing, validate_model_dimensions,
)


def png_bytes(size=(1280,720)):
    b=BytesIO(); Image.new("RGB",size).save(b,format="PNG"); return b.getvalue()


def make_project(root: Path, name="p", count=2):
    p=root/name; p.mkdir()
    blocks=[]
    rows=["scene_id,recommended_asset_type,image_prompt_id"]
    for i in range(1,count+1):
        blocks.append(f"### IMAGE {i:03d}\n\n- Filename: image_{i:03d}.png\n- image_prompt_id: IMG-{i:03d}\n- Scene ID: S{i:03d}\n- Script Context: ordinary narration {i}\n- Narrative Context: home context {i}\n- Final AI IMAGE PROMPT: Photorealistic older adult at home doing ordinary action {i}. No embedded readable text.\n")
        rows.append(f"S{i:03d},AI_IMAGE,IMG-{i:03d}")
    (p/'10_image_prompts.md').write_text('# Image Prompts\n\n'+'\n'.join(blocks))
    (p/'07_production_sheet.csv').write_text('\n'.join(rows)+'\n')
    return p


def requester(_key, _profile, _prompt, _timeout): return png_bytes(), 0.001


def test_profile_and_filenames_and_original_immutable(tmp_path):
    p=make_project(tmp_path)
    before=(p/'10_image_prompts.md').read_bytes(); before_hash=hashlib.sha256(before).hexdigest()
    a=load_production_image_assignments(p)
    assert MODEL_PROFILES[DEFAULT_MODEL_KEY].model_id == 'prunaai:p-image@ideogram'
    assert MODEL_PROFILES['flux-1-schnell'].model_id == 'runware:100@1'
    assert [x.filename for x in a] == ['image_001.png','image_002.png']
    enhanced=enhance_prompt(a[0].original_prompt, MODEL_PROFILES[DEFAULT_MODEL_KEY], True)
    assert enhanced.startswith(a[0].original_prompt)
    assert enhance_prompt(a[0].original_prompt, MODEL_PROFILES[DEFAULT_MODEL_KEY], False) == a[0].original_prompt
    assert hashlib.sha256((p/'10_image_prompts.md').read_bytes()).hexdigest()==before_hash


def test_project_isolation_missing_and_generation(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNWARE_API_KEY','secret-test-key')
    a=make_project(tmp_path,'a',1); b=make_project(tmp_path,'b',3)
    aa=load_production_image_assignments(a); bb=load_production_image_assignments(b)
    assert aa[0].asset_path.parent == a.resolve()/'assets'/'images'
    assert bb[0].asset_path.parent == b.resolve()/'assets'/'images'
    (a/'assets/images').mkdir(parents=True); (a/'assets/images/image_001.png').write_bytes(png_bytes())
    assert select_missing(aa)==[] and len(select_missing(bb))==3
    results=generate_batch(b, bb[:1], MODEL_PROFILES[DEFAULT_MODEL_KEY], requester=requester, max_workers=1)
    assert results[0].status=='SUCCESS'
    assert (b/'assets/images/image_001.png').is_file()
    assert not (a/'assets/images/image_002.png').exists()


def test_regenerate_selected_style_target_only(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNWARE_API_KEY','secret-test-key')
    p=make_project(tmp_path,count=2); assignments=load_production_image_assignments(p)
    (p/'assets/images').mkdir(parents=True)
    (p/'assets/images/image_001.png').write_bytes(png_bytes((640,360)))
    (p/'assets/images/image_002.png').write_bytes(png_bytes((640,360)))
    old2=(p/'assets/images/image_002.png').read_bytes()
    generate_batch(p,[assignments[0]],MODEL_PROFILES[DEFAULT_MODEL_KEY],requester=requester,max_workers=1)
    assert (p/'assets/images/image_001.png').stat().st_size != len(old2)
    assert (p/'assets/images/image_002.png').read_bytes()==old2


def test_failure_retry_and_no_secret_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNWARE_API_KEY','TOPSECRET')
    p=make_project(tmp_path,count=1); a=load_production_image_assignments(p)[0]; calls={'n':0}
    def flaky(_key,_profile,_prompt,_timeout):
        calls['n']+=1
        if calls['n']==1: raise TimeoutError('temporary timeout TOPSECRET')
        return png_bytes(),None
    result=generate_batch(p,[a],MODEL_PROFILES[DEFAULT_MODEL_KEY],retry_count=1,requester=flaky,max_workers=1)[0]
    assert result.status=='SUCCESS' and result.attempts==2
    raw=(p/'image_generation_manifest.json').read_text()
    assert 'TOPSECRET' not in raw


def test_stale_detection_and_manifest_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNWARE_API_KEY','x')
    p=make_project(tmp_path,count=1); a=load_production_image_assignments(p)
    generate_batch(p,a,MODEL_PROFILES[DEFAULT_MODEL_KEY],requester=requester,max_workers=1)
    m=load_manifest(p)['images']['image_001.png']
    assert m['original_prompt_hash'] and m['enhanced_prompt_hash'] and m['output_sha256']
    text=(p/'10_image_prompts.md').read_text().replace('ordinary action 1','different approved action 1')
    (p/'10_image_prompts.md').write_text(text)
    changed=load_production_image_assignments(p); m2=reconcile_manifest(p,changed)
    assert m2['images']['image_001.png']['status']=='STALE'


def test_invalid_output_never_success(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNWARE_API_KEY','x')
    p=make_project(tmp_path,count=1); a=load_production_image_assignments(p)
    def bad(*args): return b'not an image',None
    r=generate_batch(p,a,MODEL_PROFILES[DEFAULT_MODEL_KEY],requester=bad,max_workers=1)[0]
    assert r.status=='FAILED' and not (p/'assets/images/image_001.png').exists()


def test_zip_exact_names(tmp_path):
    p=make_project(tmp_path,count=2); a=load_production_image_assignments(p)
    (p/'assets/images').mkdir(parents=True)
    for x in a: x.asset_path.write_bytes(png_bytes())
    z=zipfile.ZipFile(BytesIO(build_images_zip(p,a)))
    assert z.namelist()==['image_001.png','image_002.png']


def test_filename_mapping_normalizes_only_in_generation_layer_to_timeline_contract(tmp_path):
    p = make_project(tmp_path, count=100)
    prompt_path = p / '10_image_prompts.md'
    text = prompt_path.read_text()
    # Reproduce the live Production formatting mismatch: two digits below 100.
    for i in range(1, 100):
        text = text.replace(f'- Filename: image_{i:03d}.png', f'- Filename: image_{i:02d}.png')
    prompt_path.write_text(text)
    before = prompt_path.read_bytes()

    assignments = load_production_image_assignments(p)
    by_number = {a.image_number: a for a in assignments}
    assert by_number[1].filename == 'image_001.png'
    assert by_number[9].filename == 'image_009.png'
    assert by_number[10].filename == 'image_010.png'
    assert by_number[99].filename == 'image_099.png'
    assert by_number[100].filename == 'image_100.png'
    assert prompt_path.read_bytes() == before
    assert not (p / 'assets/images/image_01.png').exists()


def test_filename_mapping_honors_explicit_selected_asset_path_padding(tmp_path):
    p = make_project(tmp_path, count=100)
    sheet = p / '07_production_sheet.csv'
    rows = ['scene_id,recommended_asset_type,image_prompt_id,selected_asset_path']
    for i in range(1, 101):
        # Simulate an established two-digit contract below 100 and natural 3 digits at 100.
        filename = f'image_{i:02d}.png' if i < 100 else 'image_100.png'
        rows.append(f'S{i:03d},AI_IMAGE,IMG-{i:03d},assets/images/{filename}')
    sheet.write_text('\n'.join(rows) + '\n')

    assignments = load_production_image_assignments(p)
    by_number = {a.image_number: a for a in assignments}
    assert by_number[1].filename == 'image_01.png'
    assert by_number[9].filename == 'image_09.png'
    assert by_number[10].filename == 'image_10.png'
    assert by_number[99].filename == 'image_99.png'
    assert by_number[100].filename == 'image_100.png'
    for number in (1, 9, 10, 99, 100):
        assert by_number[number].asset_path == (p / 'assets/images' / by_number[number].filename).resolve()


def test_schnell_profile_uses_expected_model_and_valid_dimensions():
    profile = MODEL_PROFILES['flux-1-schnell']
    assert profile.model_id == 'runware:100@1'
    assert profile.dimensions == (1344, 768)
    width, height = profile.dimensions
    assert width % 64 == 0
    assert height % 64 == 0
    assert 128 <= width <= 2048
    assert 128 <= height <= 2048
    validate_model_dimensions(profile)


def test_p_image_profile_dimensions_remain_unchanged():
    assert MODEL_PROFILES['p-image-ideogram'].dimensions == (1280, 720)


def test_runware_request_uses_selected_model_profile_dimensions(monkeypatch):
    captured = {}

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return self.payload

    def fake_urlopen(request, timeout=120):
        if hasattr(request, 'data') and request.data:
            task = json.loads(request.data.decode('utf-8'))[0]
            captured.update(task)
            return FakeResponse(json.dumps({'data':[{'imageURL':'https://example.invalid/image.png','cost':0.001}]}).encode())
        return FakeResponse(png_bytes(MODEL_PROFILES['flux-1-schnell'].dimensions))

    monkeypatch.setattr('image_generation.urllib.request.urlopen', fake_urlopen)
    profile = MODEL_PROFILES['flux-1-schnell']
    _runware_request('test-key', profile, 'unchanged prompt')
    assert captured['model'] == 'runware:100@1'
    assert captured['width'] == 1344
    assert captured['height'] == 768
    assert captured['positivePrompt'] == 'unchanged prompt'


def test_invalid_schnell_dimensions_rejected_before_requester_submission(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNWARE_API_KEY', 'test-key')
    p = make_project(tmp_path, count=1)
    assignment = load_production_image_assignments(p)[0]
    invalid = ModelProfile(
        key='flux-invalid', display_name='FLUX.1 Schnell', provider='Runware',
        model_id='runware:100@1', dimensions=(1280, 720),
    )
    calls = {'n': 0}
    def must_not_run(*args):
        calls['n'] += 1
        raise AssertionError('requester must not be called for invalid Schnell dimensions')
    result = generate_batch(p, [assignment], invalid, requester=must_not_run, max_workers=1)[0]
    assert result.status == 'FAILED'
    assert result.attempts == 0
    assert calls['n'] == 0
    assert 'multiples of 64' in result.error
    assert not assignment.asset_path.exists()


def test_schnell_generation_uses_profile_dimensions_without_changing_prompt_or_filename(tmp_path, monkeypatch):
    monkeypatch.setenv('RUNWARE_API_KEY', 'test-key')
    p = make_project(tmp_path, count=1)
    assignment = load_production_image_assignments(p)[0]
    original_prompt = assignment.original_prompt
    original_filename = assignment.filename
    seen = {}
    def profile_requester(_key, profile, prompt, _timeout):
        seen['model'] = profile.model_id
        seen['dimensions'] = profile.dimensions
        seen['prompt'] = prompt
        return png_bytes(profile.dimensions), 0.001
    result = generate_batch(
        p, [assignment], MODEL_PROFILES['flux-1-schnell'],
        enhancement_enabled=False, requester=profile_requester, max_workers=1,
    )[0]
    assert result.status == 'SUCCESS'
    assert seen == {
        'model': 'runware:100@1',
        'dimensions': (1344, 768),
        'prompt': original_prompt,
    }
    assert assignment.filename == original_filename == 'image_001.png'
    with Image.open(assignment.asset_path) as image:
        assert image.size == (1344, 768)
