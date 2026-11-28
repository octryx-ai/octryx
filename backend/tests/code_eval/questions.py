"""The code questions about spring-petclinic at the pinned commit, with their known answers."""

from __future__ import annotations

from dataclasses import dataclass

_JAVA = "src/main/java/org/springframework/samples/petclinic"
_TEST = "src/test/java/org/springframework/samples/petclinic"


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    text: str
    facts: tuple[str, ...]
    files: tuple[str, ...]
    truth: tuple[tuple[str, str], ...]
    search_queries: tuple[str, ...] = ()


QUESTIONS = (
    Question(
        "owner_creation",
        "In spring-petclinic, which class handles owner creation, and which URL does it map?",
        (r"OwnerController", r"/owners/new"),
        (f"{_JAVA}/owner/OwnerController.java",),
        ((f"{_JAVA}/owner/OwnerController.java", '@GetMapping("/owners/new")'),
         (f"{_JAVA}/owner/OwnerController.java", '@PostMapping("/owners/new")')),
    ),
    Question(
        "build_versions",
        "Which Spring Boot version and which Java version does the spring-petclinic pom.xml declare?",
        (r"3\.5\.6", r"\b17\b"),
        ("pom.xml",),
        (("pom.xml", "<version>3.5.6</version>"), ("pom.xml", "<java.version>17</java.version>")),
    ),
    Question(
        "entities",
        "Which JPA entities exist in spring-petclinic, and how are Pet and Visit related?",
        (r"\bOwner\b", r"\bPet\b", r"\bVisit\b", r"\bVet\b", r"PetType", r"Specialty",
         r"one[- ]to[- ]many|@?OneToMany"),
        (f"{_JAVA}/owner/Pet.java", f"{_JAVA}/owner/Visit.java"),
        ((f"{_JAVA}/owner/Pet.java", "@OneToMany"), (f"{_JAVA}/owner/Pet.java", "Set<Visit> visits"),
         (f"{_JAVA}/owner/Visit.java", "@Entity"), (f"{_JAVA}/owner/Owner.java", "@Entity"),
         (f"{_JAVA}/vet/Vet.java", "@Entity"), (f"{_JAVA}/vet/Specialty.java", "@Entity"),
         (f"{_JAVA}/owner/PetType.java", "@Entity")),
        ("spring-petclinic jakarta.persistence.Entity", "spring-petclinic Pet Visit relationship"),
    ),
    Question(
        "pet_validation",
        "Where is validation for pets implemented in spring-petclinic, and how is it wired in?",
        (r"PetValidator", r"InitBinder|setValidator"),
        (f"{_JAVA}/owner/PetValidator.java", f"{_JAVA}/owner/PetController.java"),
        ((f"{_JAVA}/owner/PetValidator.java", "implements Validator"),
         (f"{_JAVA}/owner/PetController.java", "setValidator(new PetValidator())")),
    ),
    Question(
        "caching",
        "Which caching configuration exists in spring-petclinic?",
        (r"CacheConfiguration", r"EnableCaching", r"\bvets\b", r"JCache|javax\.cache"),
        (f"{_JAVA}/system/CacheConfiguration.java", f"{_JAVA}/vet/VetRepository.java"),
        ((f"{_JAVA}/system/CacheConfiguration.java", "@EnableCaching"),
         (f"{_JAVA}/system/CacheConfiguration.java", 'createCache("vets"'),
         (f"{_JAVA}/vet/VetRepository.java", '@Cacheable("vets")')),
    ),
    Question(
        "vet_specialties",
        "In spring-petclinic, how are vets and their specialties related, and through which join table?",
        (r"many[- ]to[- ]many|@?ManyToMany", r"vet_specialties"),
        (f"{_JAVA}/vet/Vet.java",),
        ((f"{_JAVA}/vet/Vet.java", "@ManyToMany"), (f"{_JAVA}/vet/Vet.java", 'name = "vet_specialties"')),
    ),
    Question(
        "test_mocks",
        "Which annotation do the spring-petclinic controller tests use to mock repositories?",
        (r"MockitoBean",),
        (f"{_TEST}/owner/OwnerControllerTests.java", f"{_TEST}/vet/VetControllerTests.java",
         f"{_TEST}/owner/PetControllerTests.java", f"{_TEST}/owner/VisitControllerTests.java"),
        ((f"{_TEST}/owner/OwnerControllerTests.java", "@MockitoBean"),
         (f"{_TEST}/vet/VetControllerTests.java", "@MockitoBean"),
         (f"{_TEST}/owner/PetControllerTests.java", "@MockitoBean"),
         (f"{_TEST}/owner/VisitControllerTests.java", "@MockitoBean")),
    ),
)

# Two code repositories are active, so explicit selection is required.
IMPACT_QUESTION = "What has to change in spring-petclinic for Spring Boot 4?"
IMPACT_PRODUCT = "spring-boot"

__all__ = ["IMPACT_PRODUCT", "IMPACT_QUESTION", "QUESTIONS", "Question"]
