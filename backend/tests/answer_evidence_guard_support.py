"""Synthetic petclinic web-fetch evidence and cited/uncited answers shared by the answer evidence guard tests."""

from __future__ import annotations

PETCLINIC_OWNER = "https://raw.githubusercontent.com/spring-projects/spring-petclinic/4f1b2c3/src/main/java/org/springframework/samples/petclinic/owner/Owner.java"


def _web_fetch_result() -> dict:
    return {
        "tool_name": "web_fetch",
        "params": {"url": PETCLINIC_OWNER},
        "result": {
            "url": PETCLINIC_OWNER,
            "source_title": "Owner.java",
            "source_url": PETCLINIC_OWNER,
            "cite_as": f"[Owner.java]({PETCLINIC_OWNER})",
            "content": '@OneToMany(cascade = CascadeType.ALL)\n@OrderBy("name")\nprivate final List<Pet> pets',
            "format": "text",
        },
    }


UNCITED_PETCLINIC = (
    "The Owner entity has a bidirectional one-to-many relation to Pet, ordered with "
    '`@OrderBy("visit_date ASC")`.\n\n'
    "- The model has 5 entities: Owner, Pet, PetType, Visit, Vet and Specialty.\n"
)


CITED_PETCLINIC = (
    f'The Owner entity holds a one-to-many list of pets ordered with `@OrderBy("name")` ([Owner.java]({PETCLINIC_OWNER})).\n'
)
