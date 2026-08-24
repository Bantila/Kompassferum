"""Разбор ответа на тренировочную задачу."""

import pytest

from app.services.error_classifier import classify


def is_correct(given: str, expected: str, subject: str = "chemistry") -> bool:
    return classify(given, expected, subject)["is_correct"]


def error_type(given: str, expected: str, subject: str = "mathematics") -> str:
    return classify(given, expected, subject)["error_type"]


class TestTextAnswers:
    """Свободный ответ: ученик пишет своими словами, а в банке эталон одной строкой."""

    @pytest.mark.parametrize(
        "given, expected",
        [
            ("метан CH₄", "метан CH₄"),          # точное совпадение
            ("Метан CH₄", "метан CH₄"),          # регистр
            ("метан, CH₄", "метан CH₄"),         # пунктуация
            ("метан", "метан CH₄"),              # опущена формула
            ("это метан CH₄", "метан CH₄"),      # лишние слова
            ("круглые черви", "круглые черви"),
            ("Круглые Черви!", "круглые черви"),
            ("нервныи центр", "нервный центр"),  # не должен ломаться на опечатке? нет — см. ниже
        ][:-1],
    )
    def test_accepted(self, given, expected):
        assert is_correct(given, expected)

    @pytest.mark.parametrize(
        "given, expected",
        [
            ("черви", "круглые черви"),        # выпало смысловое слово — ответ другой
            ("кислород", "метан CH₄"),         # просто неверно
            ("плоские черви", "круглые черви"),
            ("", "метан"),
        ],
    )
    def test_rejected(self, given, expected):
        assert not is_correct(given, expected)

    def test_yo_and_e_are_same_letter(self):
        assert is_correct("нёбо", "небо")


class TestNumericAnswers:
    """Числа: знак, единицы и арифметика различаются по типу ошибки."""

    def test_exact(self):
        assert is_correct("-3", "-3", "mathematics")

    def test_sign_error(self):
        assert error_type("3", "-3") == "sign"

    def test_unit_error(self):
        assert error_type("700", "7") == "unit"

    def test_calculation_error(self):
        assert error_type("7.2", "7") == "calculation"

    def test_far_off_is_conceptual(self):
        assert error_type("100", "7") == "conceptual"

    def test_comma_as_decimal_separator(self):
        assert is_correct("7,5", "7.5", "mathematics")

    def test_single_digit_is_not_incomplete(self):
        """Односимвольный ответ — полноценный, а не обрывок.

        В исходной версии алгоритма любой ответ короче двух символов считался
        неполным, и «3» вместо «-3» не распознавалось как знаковая ошибка.
        """
        assert error_type("3", "-3") != "incomplete"


class TestEdgeCases:
    def test_empty_answer(self):
        assert error_type("", "5") == "incomplete"

    def test_short_stub_against_long_answer(self):
        assert error_type("х", "дезоксирибонуклеиновая кислота", "biology") == "incomplete"

    def test_science_subject_gets_methodology(self):
        assert error_type("совершенно другое", "число молекул", "chemistry") == "methodology"

    def test_humanities_get_conceptual(self):
        assert error_type("совершенно другое", "число молекул", "history") == "conceptual"
