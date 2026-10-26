"""The two previous questions a turn's lookups use (OdieRunner._recent_questions) are read from the session after a
restart: a form's answer there is its line only, never the fence the model reads."""
from odie.app.runner import previous_questions


def test_previous_questions_drop_form_answer_fences_and_keep_the_last_two_newest_first():
    answer = 'Where: Hills · Pace: 40%\n\n```odie-form-answer\n{"form": "trip", "values": {"where": "Hills"}}\n```'
    history = [{"role": "user", "text": "Plan a trip"}, {"role": "odie", "text": "A form"},
               {"role": "user", "text": answer}, {"role": "user", "text": ""}, {"role": "user", "text": "Thanks"}]
    assert previous_questions(history) == ["Thanks", "Where: Hills · Pace: 40%"]
