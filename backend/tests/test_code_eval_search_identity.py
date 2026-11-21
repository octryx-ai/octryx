"""Source identity may carry a code name; body evidence must still carry its behavior."""

from tests.code_eval import answers, questions
from tests.code_eval.repos import PETCLINIC


def test_source_identity_supports_a_name_without_replacing_relation_evidence():
    repo = PETCLINIC
    path = "src/main/java/org/springframework/samples/petclinic/vet/Specialty.java"
    question = questions.Question("identity", "Which entity?", ("Specialty", "@Entity"), (path,), ())
    payload = {"evidence": [{"text": "@Entity", "source_title": path,
                              "source_url": repo.blob_url(path) + "#L20-L21"}]}
    assert answers.judge_search(question, payload, repo, frozenset({path})).ok
    relation = questions.Question("relation", "How related?", ("Specialty", "@OneToMany"), (path,), ())
    assert not answers.judge_search(relation, payload, repo, frozenset({path})).ok
    payload["evidence"][0]["source_url"] = "https://example.com/unrelated"
    assert not answers.judge_search(question, payload, repo, frozenset({path})).ok
