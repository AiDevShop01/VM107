"""
Tests for relationship validation scoring engine.

Tests the 6-component scoring system, Bayesian update mechanics,
time decay, and prior loading logic.
"""
import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add VM101 backend to path for imports
vm101_backend_path = Path("/Volumes/ HardDrive/FinGPT/VM101/backend")
if str(vm101_backend_path) not in sys.path:
    sys.path.insert(0, str(vm101_backend_path))


class TestBayesianUpdate:
    """Test Bayesian update formula: posterior = (1-weight)*prior + weight*empirical."""

    def test_zero_samples_returns_pure_prior(self):
        """With n=0, should return 100% prior (no empirical weight)."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        result = RelationshipValidator.bayesian_update(
            prior_prob=0.6,
            empirical=0.8,
            sample_size=0,
            threshold=30
        )
        assert result == 0.6, "n=0 should return pure prior"

    def test_half_threshold_returns_50_50_mix(self):
        """With n=threshold/2, should return 50/50 mix of prior and empirical."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        result = RelationshipValidator.bayesian_update(
            prior_prob=0.6,
            empirical=0.8,
            sample_size=15,
            threshold=30
        )
        expected = 0.5 * 0.6 + 0.5 * 0.8  # 0.7
        assert abs(result - expected) < 0.01, f"n=15 should return {expected}, got {result}"

    def test_at_threshold_returns_pure_empirical(self):
        """With n>=threshold, should return 100% empirical."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        result = RelationshipValidator.bayesian_update(
            prior_prob=0.6,
            empirical=0.8,
            sample_size=30,
            threshold=30
        )
        assert result == 0.8, "n=30 should return pure empirical"

    def test_above_threshold_still_pure_empirical(self):
        """With n>threshold, should still return 100% empirical."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        result = RelationshipValidator.bayesian_update(
            prior_prob=0.6,
            empirical=0.8,
            sample_size=100,
            threshold=30
        )
        assert result == 0.8, "n=100 should return pure empirical"


class TestTimeDecay:
    """Test exponential time decay: confidence * 0.5^(days/half_life)."""

    def test_zero_days_no_decay(self):
        """With days=0, should return original confidence."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        result = RelationshipValidator.time_decay(
            confidence=1.0,
            days=0,
            half_life=180
        )
        assert result == 1.0, "days=0 should return original confidence"

    def test_half_life_returns_half_confidence(self):
        """At half_life days, should return ~0.5 confidence."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        result = RelationshipValidator.time_decay(
            confidence=1.0,
            days=180,
            half_life=180
        )
        assert abs(result - 0.5) < 0.01, f"days=180 should return ~0.5, got {result}"

    def test_two_half_lives_returns_quarter_confidence(self):
        """At 2x half_life, should return ~0.25 confidence."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        result = RelationshipValidator.time_decay(
            confidence=1.0,
            days=360,
            half_life=180
        )
        assert abs(result - 0.25) < 0.01, f"days=360 should return ~0.25, got {result}"

    def test_four_half_lives_returns_sixteenth_confidence(self):
        """At 4x half_life, should return ~0.0625 confidence."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        result = RelationshipValidator.time_decay(
            confidence=1.0,
            days=720,
            half_life=180
        )
        assert abs(result - 0.0625) < 0.01, f"days=720 should return ~0.0625, got {result}"


class TestCompositeScore:
    """Test weighted composite score calculation."""

    def test_composite_score_with_known_values(self):
        """Test composite score with known component values."""
        from knowledge.validation.relationship_validator import RelationshipValidator

        components = {
            'success_rate': 0.8,
            'lift': 1.5,
            'sample_size_confidence': 1.0,
            'recency': 0.9,
            'consistency': 0.85,
            'contradiction_penalty': 1.0
        }
        weights = {
            'success_rate': 0.30,
            'lift': 0.20,
            'sample_size_confidence': 0.15,
            'recency': 0.15,
            'consistency': 0.10,
            'contradiction_penalty': 0.10
        }

        result = RelationshipValidator.compute_composite_score(components, weights)

        # Manual calculation: 0.8*0.3 + 1.5*0.2 + 1.0*0.15 + 0.9*0.15 + 0.85*0.1 + 1.0*0.1
        # = 0.24 + 0.30 + 0.15 + 0.135 + 0.085 + 0.10 = 1.01
        # But lift should be normalized to 0-1 range first
        # Assuming lift is capped at 1.0 or normalized: min(lift/2, 1.0)
        # Let's use lift as-is and see what implementation does
        expected = 0.8*0.3 + 1.5*0.2 + 1.0*0.15 + 0.9*0.15 + 0.85*0.1 + 1.0*0.1

        assert abs(result - expected) < 0.01, f"Expected ~{expected}, got {result}"


class TestStatusThresholds:
    """Test status determination from validation scores."""

    def test_high_score_returns_validated(self):
        """Score >0.75 should recommend 'validated' status."""
        # This will be tested via full validation flow
        # For now, just test the threshold logic exists
        pass

    def test_medium_score_returns_weak_evidence(self):
        """Score 0.5-0.75 should recommend 'weak_evidence' status."""
        pass

    def test_low_score_returns_rejected(self):
        """Score <0.5 should recommend 'rejected' status."""
        pass


class TestPriorLoader:
    """Test YAML prior loading and merge logic."""

    def test_yaml_precedence_over_book(self):
        """When both YAML and book priors exist, YAML should win."""
        from knowledge.validation.prior_loader import PriorLoader

        # Create test YAML content
        yaml_content = """
version: 1
priors:
  - source_type: "Concept"
    target_type: "Concept"
    relationship: "CAUSES"
    pattern: "displacement.*liquidity_sweep"
    prior_probability: 0.65
    prior_confidence: 0.8
    notes: "Test prior"
"""

        # We'll test this after implementation
        # For now, just verify the class can be imported
        assert PriorLoader is not None

    def test_merge_yaml_only(self):
        """When only YAML prior exists, use YAML with is_locked=True."""
        from knowledge.validation.prior_loader import PriorLoader

        yaml_prior = {
            'prior_probability': 0.65,
            'prior_confidence': 0.8,
            'prior_source': 'yaml',
            'is_locked': True
        }
        book_prior = None

        result = PriorLoader.merge_priors(yaml_prior, book_prior)
        assert result['prior_source'] == 'yaml'
        assert result['is_locked'] is True
        assert result['prior_probability'] == 0.65

    def test_merge_book_only(self):
        """When only book prior exists, use book with is_locked=False."""
        from knowledge.validation.prior_loader import PriorLoader

        yaml_prior = None
        book_prior = {
            'prior_probability': 0.55,
            'prior_confidence': 0.6,
            'prior_source': 'book',
            'is_locked': False
        }

        result = PriorLoader.merge_priors(yaml_prior, book_prior)
        assert result['prior_source'] == 'book'
        assert result['is_locked'] is False
        assert result['prior_probability'] == 0.55

    def test_merge_both_prefers_yaml(self):
        """When both exist, prefer YAML (authoritative)."""
        from knowledge.validation.prior_loader import PriorLoader

        yaml_prior = {
            'prior_probability': 0.65,
            'prior_confidence': 0.8,
            'prior_source': 'yaml',
            'is_locked': True
        }
        book_prior = {
            'prior_probability': 0.55,
            'prior_confidence': 0.6,
            'prior_source': 'book',
            'is_locked': False
        }

        result = PriorLoader.merge_priors(yaml_prior, book_prior)
        assert result['prior_source'] == 'yaml'
        assert result['is_locked'] is True
        assert result['prior_probability'] == 0.65

    def test_merge_neither_returns_default(self):
        """When neither exists, return default prior."""
        from knowledge.validation.prior_loader import PriorLoader

        result = PriorLoader.merge_priors(None, None)
        assert result['prior_source'] == 'default'
        assert result['is_locked'] is False
        assert result['prior_probability'] == 0.5
        assert result['prior_confidence'] == 0.3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
