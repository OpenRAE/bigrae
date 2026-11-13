"""Evaluate a rendered Kubernetes label selector against one pod label set."""


def selected(selector, labels):
    """Return whether the selector's matchLabels and matchExpressions admit the labels."""
    if any(labels.get(key) != value for key, value in selector.get("matchLabels", {}).items()):
        return False
    for expression in selector.get("matchExpressions", []):
        value = labels.get(expression["key"])
        if expression["operator"] == "NotIn" and value in expression["values"]:
            return False
        if expression["operator"] == "In" and value not in expression["values"]:
            return False
    return True
