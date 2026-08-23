from pathlib import Path
from v31_core import derive_content_promise_inventory,evaluate_content_promise,detect_content_promise_hook


def project(tmp_path: Path, body: str):
    (tmp_path/'01_topic_validation.md').write_text('# Topic\n\n## Core viewer problem\n\n'+body+'\n\n## Recommended angle\n\n'+body,encoding='utf-8')
    (tmp_path/'02_research_sheet.md').write_text('# Research\n\n## Approved Claims\n\n'+body,encoding='utf-8')
    (tmp_path/'13_fact_check_log.md').write_text('# Fact Check\n\n'+body,encoding='utf-8')
    return derive_content_promise_inventory(tmp_path)


def test_genuine_and_fabricated_mistake(tmp_path):
    inv=project(tmp_path,'Older viewers use the featured food at night. A common mistake is doubling the serving; this misuse can worsen the primary sleep problem.')
    assert evaluate_content_promise('The Night Food Mistake Most Older Adults Make',inv)[1]=='PASS'
    assert evaluate_content_promise('The Warning Signs Most Older Adults Ignore',inv)[1]=='FAIL'


def test_minor_generic_disclaimer_cannot_manufacture_warning_or_before_action(tmp_path):
    inv=project(tmp_path,'The primary problem is daily stiffness and the subject is a gentle routine. Talk to your doctor for medical advice.')
    assert evaluate_content_promise('Warning Signs You Must Not Ignore',inv)[1]=='FAIL'
    assert evaluate_content_promise('Before You Do This Routine, Read This First',inv)[1]=='FAIL'


def test_genuine_warning_and_before_action(tmp_path):
    inv=project(tmp_path,'The primary problem is dizziness during a standing routine. Stop the routine and seek evaluation for chest pain or fainting. Before standing, use support and avoid the action when dizzy.')
    assert evaluate_content_promise('Standing Routine Warning Signs Not to Ignore',inv)[1]=='PASS'
    assert evaluate_content_promise('Before You Do This Standing Routine, Read This First',inv)[1]=='PASS'


def test_number_list_supported_and_unsupported(tmp_path):
    inv=project(tmp_path,'The primary symptom may come from sleep position, dry air, meal timing, medicines, hydration, or room irritants. These six causes or contributors are the supported source map.')
    assert evaluate_content_promise('6 Possible Causes of This Daily Symptom',inv)[1]=='PASS'
    assert evaluate_content_promise('60 Possible Causes of This Daily Symptom',inv)[1]=='FAIL'


def test_cause_habit_myth_consequence_and_ordinary(tmp_path):
    inv=project(tmp_path,'The primary cough problem can come from dry air. A repeated throat-clearing habit can keep irritation going. A common misconception is that color always proves infection. Worsening choking can lead to aspiration risk.')
    assert evaluate_content_promise('The Real Source of This Cough',inv)[1]=='PASS'
    assert evaluate_content_promise('The Everyday Habit Keeping This Cough Going',inv)[1]=='PASS'
    assert evaluate_content_promise('The Cough Myth People Get Wrong',inv)[1]=='PASS'
    assert evaluate_content_promise('What Happens If This Choking Gets Worse',inv)[1]=='PASS'
    assert evaluate_content_promise('Daily Cough After 60: Simple Steps That May Help',inv)[1]=='NOT_APPLICABLE'


def test_candidate_text_immutable(tmp_path):
    inv=project(tmp_path,'The primary problem is poor sleep. A common mistake is using the subject too late at night.')
    title='The Bedtime Mistake Most Older Adults Make'
    before=title.encode(); evaluate_content_promise(title,inv); assert title.encode()==before


def test_cross_project_inventory_isolation(tmp_path):
    a=tmp_path/'a'; b=tmp_path/'b'; c=tmp_path/'c'; a.mkdir(); b.mkdir(); c.mkdir()
    ia=project(a,'The primary drink problem has a mistake: using the drink too late.')
    ib=project(b,'The primary throat problem has warning signs: blood or choking needs evaluation.')
    ic=project(c,'The primary exercise problem has a supported standing habit and balance routine.')
    assert 'drink' in ia['ALL_TEXT'].lower() and 'drink' not in ib['ALL_TEXT'].lower() and 'drink' not in ic['ALL_TEXT'].lower()
    assert evaluate_content_promise('The Throat Mistake Most People Make',ib)[1]=='FAIL'
    assert evaluate_content_promise('Exercise Warning Signs Not to Ignore',ic)[1]=='FAIL'


def test_exact_mucus_15_regression_fixture():
    p=Path('Projects/doctor-explains-why-you-always-have-mucus-in-your-throat-and-how-to-fix-it')
    inv=derive_content_promise_inventory(p)
    titles=[
    "Always Feel Mucus in Your Throat After 60? Here's Where It May Really Be Coming From",
    "Constant Mucus in Your Throat? 6 Places It May Actually Start (It's Not Always Your Throat)",
    "Why You Always Have Mucus in Your Throat After 60 (And What May Help Depending on the Cause)",
    "That Constant Throat Clearing After 60: What It May Mean and What to Check First",
    "Over 60 and Always Clearing Your Throat? It May Not Be Extra Mucus at All",
    "Mucus in Your Throat Every Morning After 60? The Real Source May Surprise You",
    'Why That "Lump" or Mucus Feeling in Your Throat Won\'t Go Away After 60',
    "Constant Throat Mucus After 60: Nose, Stomach, or Something Else Entirely?",
    "Always Have Phlegm in Your Throat? What May Help And When It Needs a Closer Look",
    "The Everyday Habit That May Keep the Mucus-in-Throat Feeling Going After 60",
    "Why You Keep Clearing Your Throat After 60 (And the Warning Signs Not to Ignore)",
    "Mucus in the Throat After 60: Why It Happens and Simple Steps That May Help",
    "If You Always Feel Mucus in Your Throat, It May Be Coming From Somewhere You'd Never Guess",
    "Constant Throat Mucus After 60: 6 Possible Causes and What to Try First",
    "Why Your Throat Always Feels Full of Mucus After 60 And When to Get It Checked"]
    results=[evaluate_content_promise(t,inv) for t in titles]
    assert len(results)==15
    assert results[1][1]=='PASS' and 'NUMBER_LIST:' in results[1][2] and 'distinct_supported=' in results[1][2]
    assert results[7][0]=='CAUSE_SOURCE' and results[7][1]=='PASS'
    assert results[9][0]=='HABIT' and results[9][1]=='PASS'
    assert results[10][0]=='WARNING' and results[10][1]=='PASS'
    assert inv['source_reads']==3


def test_number_list_distinct_causes_pass_and_repeated_evidence_fails(tmp_path):
    p=tmp_path/'seven'; p.mkdir()
    inv=project(p,'The primary symptom has several supported causes. Causes: dry air, late meals, medicine effects, dehydration, smoke exposure, infection, swallowing changes.')
    hook,bond,reason=evaluate_content_promise('6 Possible Causes of This Symptom',inv)
    assert bond=='PASS' and 'category=CAUSE' in reason and 'distinct_supported=7' in reason

    q=tmp_path/'five'; q.mkdir()
    repeated=' '.join(['Causes: dry air, late meals, medicine effects, dehydration, smoke exposure.']*100)
    inv2=project(q,'The primary symptom has five supported causes. '+repeated)
    hook,bond,reason=evaluate_content_promise('6 Possible Causes of This Symptom',inv2)
    assert bond=='FAIL' and 'distinct_supported=5' in reason


def test_number_list_cross_source_duplicates_and_surface_paraphrases_count_once(tmp_path):
    # The same semantic concepts recur in all three authorized files via project(); exact and surface-near forms must not inflate.
    inv=project(tmp_path,'Causes: nasal drainage, postnasal drainage, dry air, reflux irritation, medicine effects, dehydration.')
    assert len(inv['SEMANTIC_ITEMS']['CAUSE'])==5
    assert evaluate_content_promise('6 Possible Causes',inv)[1]=='FAIL'


def test_number_list_exercises_exact_count(tmp_path):
    p=tmp_path/'five'; p.mkdir()
    inv=project(p,'The primary mobility topic has a supported routine. Exercises: heel raises, ankle pumps, seated marching, sit to stand, supported side steps.')
    assert evaluate_content_promise('5 Exercises for This Routine',inv)[1]=='PASS'
    q=tmp_path/'four'; q.mkdir()
    inv2=project(q,'The primary mobility topic has a supported routine. Exercises: heel raises, ankle pumps, seated marching, sit to stand.')
    assert evaluate_content_promise('5 Exercises for This Routine',inv2)[1]=='FAIL'


def test_number_list_warning_signs_repeated_mentions_do_not_inflate(tmp_path):
    body='Warning signs: fainting, chest pain. ' + ' '.join(['Warning signs include fainting and chest pain.']*40)
    inv=project(tmp_path,body)
    hook,bond,reason=evaluate_content_promise('3 Warning Signs Not to Ignore',inv)
    assert bond=='FAIL' and 'category=WARNING_SIGN' in reason and 'distinct_supported=2' in reason


def test_number_list_four_unrelated_project_categories_and_isolation(tmp_path):
    specs=[
        ('a','Causes: dry air, meal timing, medicines, hydration, smoke, infection, swallowing changes.','6 Possible Causes','PASS'),
        ('b','Exercises: heel raises, ankle pumps, seated marching, sit to stand, side steps.','5 Exercises','PASS'),
        ('c','Foods: oats, berries, lentils, eggs.','4 Foods','PASS'),
        ('d','Warning signs: fainting, chest pain, severe breathlessness. Mistakes: doubling a serving, skipping safety support, changing medicine alone, ignoring dizziness, rushing progression.','3 Warning Signs','PASS'),
    ]
    inventories=[]
    for name,body,title,expected in specs:
        p=tmp_path/name; p.mkdir(); inv=project(p,body); inventories.append(inv)
        assert evaluate_content_promise(title,inv)[1]==expected
    # Same process/session: A vocabulary cannot survive into B.
    assert 'dry air' in inventories[0]['ALL_TEXT'].lower()
    assert 'dry air' not in inventories[1]['ALL_TEXT'].lower()
    assert 'CAUSE' not in inventories[1]['SEMANTIC_ITEMS']
    assert evaluate_content_promise('6 Possible Causes',inventories[1])[1]=='FAIL'
    assert evaluate_content_promise('5 Exercises',inventories[0])[1]=='FAIL'


def test_number_list_unresolved_category_fails_without_generic_trace_fallback(tmp_path):
    inv=project(tmp_path,'The primary topic has many traceable facts and repeated evidence fragments but no supported numeric category.')
    hook,bond,reason=evaluate_content_promise('5 Widgets to Know',inv)
    assert bond=='FAIL' and 'NUMBER_LIST_UNRESOLVED_CATEGORY' in reason
