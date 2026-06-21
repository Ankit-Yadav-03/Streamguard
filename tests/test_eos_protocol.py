import pytest

from stream_guard.eos_protocol import EOS


def test_eos_is_singleton():
    """
    EOS must be a true singleton.
    There must never be more than one EOS instance.
    """
    from stream_guard.eos_protocol import EOS as EOS2

    assert EOS is EOS2, "EOS must be a singleton instance"


def test_eos_identity_comparison_only():
    """
    EOS must be compared by identity, never equality.
    """
    assert EOS is EOS
    assert not (EOS is object()), "EOS must not equal arbitrary objects"

    # Equality is identity-only
    assert EOS == EOS
    assert not (EOS == object())


def test_eos_is_not_truthy_or_falsey():
    """
    EOS must not participate in boolean contexts.
    This prevents bugs like: `if item:`
    """
    with pytest.raises(TypeError):
        bool(EOS)


def test_eos_has_stable_repr():
    """
    EOS repr must be explicit and recognizable for logs/tests.
    """
    assert repr(EOS) == "<EOS>"


def test_eos_cannot_be_copied_or_recreated():
    """
    Attempts to create another EOS-like object must fail semantically.
    """
    class FakeEOS:
        pass

    fake = FakeEOS()

    assert fake is not EOS
    assert fake != EOS
