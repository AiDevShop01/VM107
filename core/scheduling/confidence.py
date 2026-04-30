"""
EMA confidence scorer with contradiction penalty.

Tracks evidence quality via exponential moving average.
Applies contradiction penalty to reduce confidence when conflicting signals present.
"""


class ConfidenceScorer:
    """
    EMA-smoothed confidence with contradiction penalty.

    Confidence formula:
    1. EMA update: EMA_t = α × new_value + (1 - α) × EMA_{t-1}
    2. Contradiction penalty: C_final = EMA × (1 - λ × contradiction_ratio)
    3. Min sample weighting: C_final × (sample_count / min_samples) if sample_count < min_samples

    All outputs clamped to [0, 1].
    """

    def __init__(self, span: int = 20, lambda_penalty: float = 0.5, min_samples: int = 5):
        """
        Args:
            span: EMA smoothing span (larger = slower response). alpha = 2/(span+1)
            lambda_penalty: Contradiction penalty weight (0-1). Higher = more penalty
            min_samples: Minimum samples before full confidence. Early values weighted down
        """
        self.span = span
        self.alpha = 2 / (span + 1)  # EMA smoothing factor
        self.lambda_penalty = lambda_penalty
        self.min_samples = min_samples

        # State
        self._ema_confidence: float | None = None
        self._sample_count: int = 0

    def update(self, validation_result: bool, contradiction_ratio: float) -> float:
        """
        Update confidence score with new validation evidence.

        Args:
            validation_result: True if validation passed, False if failed
            contradiction_ratio: Ratio of contradicting evidence (0-1)

        Returns:
            Updated confidence score (0-1) with all adjustments applied
        """
        # Convert boolean to confidence value
        new_confidence = 1.0 if validation_result else 0.0

        # Update EMA (first value initializes EMA)
        if self._ema_confidence is None:
            self._ema_confidence = new_confidence
        else:
            # EMA formula: EMA_t = α × Price_t + (1 - α) × EMA_{t-1}
            self._ema_confidence = (
                self.alpha * new_confidence +
                (1 - self.alpha) * self._ema_confidence
            )

        self._sample_count += 1

        # Apply contradiction penalty
        # C_final = EMA_confidence × (1 - λ × contradiction_ratio)
        penalized_confidence = self._ema_confidence * (1 - self.lambda_penalty * contradiction_ratio)

        # Early cycles: weight down confidence (minimum sample size)
        if self._sample_count < self.min_samples:
            penalized_confidence *= (self._sample_count / self.min_samples)

        # Clamp to [0, 1]
        return max(0.0, min(1.0, penalized_confidence))

    def get_current(self) -> float:
        """Get current EMA confidence score (before penalties)."""
        if self._ema_confidence is None:
            return 0.0
        return self._ema_confidence
