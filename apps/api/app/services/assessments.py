import math


LEVEL_THRESHOLDS = (800, 950, 1100, 1250)


def expected_score(player_rating: int, question_rating: int, discrimination: float = 1.0) -> float:
    """Calculate expected probability of correct response under 2-parameter Item Response Theory (IRT)."""
    exponent = -discrimination * (player_rating - question_rating) / 400.0 * math.log(10)
    # Bound exponent to prevent numerical overflow
    exponent = max(-35.0, min(35.0, exponent))
    return 1.0 / (1.0 + math.exp(exponent))


def update_elo(
    player_rating: int,
    question_rating: int,
    correct: bool,
    *,
    player_k: int = 32,
    question_k: int = 16,
    discrimination: float = 1.0,
) -> tuple[int, int]:
    """Adaptive Bayesian Knowledge Tracing rating update informed by item discrimination."""
    player_expected = expected_score(player_rating, question_rating, discrimination)
    score_delta = (1.0 if correct else 0.0) - player_expected
    
    # Scale K-factor by discrimination factor for high-signal questions
    effective_player_k = player_k * min(1.5, max(0.6, discrimination))
    
    return (
        round(player_rating + effective_player_k * score_delta),
        round(question_rating - question_k * score_delta),
    )


def calculate_fisher_information(player_rating: int, question_rating: int, discrimination: float = 1.0) -> float:
    """Calculate Fisher Information for optimal Next-Item Selection in CAT (Computerized Adaptive Testing)."""
    p = expected_score(player_rating, question_rating, discrimination)
    # I(θ) = a^2 * P(θ) * (1 - P(θ))
    return (discrimination ** 2) * p * (1.0 - p)


def update_uncertainty(uncertainty: float, correct: bool, confidence: int) -> float:
    """Dynamic confidence and uncertainty calibration based on metacognitive alignment."""
    if confidence >= 4 and not correct:
        # High confidence but wrong answer indicates cognitive misconception: increase uncertainty
        return round(min(350.0, uncertainty * 1.08), 3)
    # Low confidence on correct answers also suggests guessing
    guess_penalty = 0.5 if (confidence <= 1 and correct) else 1.0
    reduction = (0.025 * confidence * guess_penalty) if correct else (0.015 * confidence)
    return round(max(50.0, uncertainty * (1.0 - reduction)), 3)


def level_for_rating(rating: int) -> int:
    for level, threshold in enumerate(LEVEL_THRESHOLDS, start=1):
        if rating < threshold:
            return level
    return 5


def estimate_level_range(
    rating: int, uncertainty: float, response_count: int
) -> dict[str, int | str]:
    lower = level_for_rating(round(rating - uncertainty))
    upper = level_for_rating(round(rating + uncertainty))
    width = upper - lower
    if response_count >= 8 and width <= 1:
        confidence = "high"
    elif response_count >= 4 and width <= 2:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "level_min": lower,
        "level_max": upper,
        "confidence": confidence,
    }


def should_stop_early(
    answered_questions: int,
    minimum_questions: int,
    level_min: int,
    level_max: int,
) -> bool:
    return answered_questions >= minimum_questions and level_max - level_min <= 1

