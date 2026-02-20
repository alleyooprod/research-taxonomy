"""Document classifier — routes content to the best extractor.

Uses heuristic classification to determine document type, then
dispatches to the appropriate specialized extractor.
"""
import logging

from core.extractors import product_page, pricing_page, changelog, press_release, funding_round, generic

logger = logging.getLogger(__name__)

# Minimum confidence threshold for specialized extractors
CLASSIFICATION_THRESHOLD = 0.4

# Extractor registry: (module, name) ordered by priority
EXTRACTORS = [
    (pricing_page, "pricing_page"),
    (changelog, "changelog"),
    (press_release, "press_release"),
    (funding_round, "funding_round"),
    (product_page, "product_page"),
]


def classify_content(content):
    """Classify content and return the best extractor.

    Args:
        content: Text/HTML content to classify

    Returns:
        tuple: (extractor_module, extractor_name, confidence)
    """
    if not content or not content.strip():
        return generic, "generic", 0.0

    best_extractor = None
    best_name = "generic"
    best_score = 0.0

    for extractor, name in EXTRACTORS:
        score = extractor.classify(content)
        logger.debug("Classifier: %s score = %.2f", name, score)
        if score > best_score:
            best_score = score
            best_extractor = extractor
            best_name = name

    if best_score >= CLASSIFICATION_THRESHOLD and best_extractor:
        return best_extractor, best_name, best_score

    return generic, "generic", best_score


def extract_with_classification(content, entity_name=None, model=None,
                                timeout=120, force_extractor=None):
    """Classify content and extract using the best extractor.

    Args:
        content: Text/HTML content
        entity_name: Entity name for context
        model: LLM model override
        timeout: LLM timeout
        force_extractor: Override classification with a specific extractor name
            ("product_page", "pricing_page", "generic")

    Returns:
        dict: Extraction result with _classification metadata, or None on failure
    """
    if force_extractor:
        extractor_map = {
            "product_page": product_page,
            "pricing_page": pricing_page,
            "changelog": changelog,
            "press_release": press_release,
            "funding_round": funding_round,
            "generic": generic,
        }
        extractor = extractor_map.get(force_extractor, generic)
        extractor_name = force_extractor
        confidence = 1.0  # forced
    else:
        extractor, extractor_name, confidence = classify_content(content)

    logger.info("Using %s extractor (confidence: %.2f)", extractor_name, confidence)

    result = extractor.extract(content, entity_name, model, timeout)
    if result:
        result["_classification"] = {
            "extractor": extractor_name,
            "classification_confidence": confidence,
        }
    return result


def get_available_extractors():
    """Return list of available extractor names."""
    return ["product_page", "pricing_page", "changelog", "press_release", "funding_round", "generic"]
