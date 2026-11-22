class MissingTokensError(Exception):
    """Отсутствуют обязательные переменные окружения."""


class ApiAnswerError(Exception):
    """Исключение при некорректном ответе API."""
