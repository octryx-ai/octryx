"""Deterministic display-name rules for AWS diagram nodes."""

from app.services.diagrams.aws_diagram_naming import display_name, normalize_label


def test_name_tag_wins_over_normalization():
    node = {"name": "Core VPC", "label": "vpc-0eccf8eace0f515cf", "type": "vpc"}
    assert display_name(node) == "Core VPC"


def test_bare_resource_ids_are_shortened():
    assert normalize_label("rtb-06ebf30a3ded0d936") == "rtb-…d0d936"
    assert normalize_label("subnet-004d832626217a4c2") == "subnet-…17a4c2"
    assert normalize_label("igw-077756accc13cb406") == "igw-…3cb406"


def test_k8s_generated_names_lose_prefix_and_hash():
    assert normalize_label("k8s-argocd-argocdar-0d2ef54549", "target_group") == "argocd-argocdar"
    assert normalize_label("k8s-defaultprivate-0963237e1e", "load_balancer") == "defaultprivate"
    # namespace equals name -> collapsed
    assert normalize_label("k8s-traefike-traefike-091cdee3bc", "target_group") == "traefike"


def test_generated_suffixes_are_stripped():
    assert normalize_label("default-ng-2024081521081053810000000c", "eks_nodegroup") == "default-ng"
    assert (
        normalize_label(
            "eks-default-ng-2024081521081053810000000c-e0c8abef-4a6c-8251-046f-bc48a1d1c091",
            "autoscaling_group",
        )
        == "default-ng"
    )


def test_real_names_stay_untouched():
    assert normalize_label("demo-nonprod-eks", "eks_cluster") == "demo-nonprod-eks"
    assert normalize_label("demo-nonprod-rds-shop-stg", "rds_instance") == (
        "demo-nonprod-rds-shop-stg"
    )
    assert normalize_label("DEMO_LVD_Card_Hist", "dynamodb_table") == "DEMO_LVD_Card_Hist"
