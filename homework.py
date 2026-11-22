# Стандартный python
import os
import http
import random
import logging
import sys
import time
from logging.handlers import RotatingFileHandler

# Сторонние, устанавливаемые
import requests  # type: ignore
import vk_api  # type: ignore
from vk_api.exceptions import ApiError  # type: ignore
from dotenv import load_dotenv  # type: ignore

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
VK_TOKEN = os.getenv('VK_TOKEN')
VK_USER_ID = os.getenv('VK_USER_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

# указываем настройки логгера для текущего файла
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # Обработчик для вывода логов в стандартный поток
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.DEBUG)

    # Обработчик для записи в файл
    file_handler = RotatingFileHandler(
        'homework.log', maxBytes=50000000, backupCount=5)
    file_handler.setLevel(logging.DEBUG)

    # Форматирование логов
    formatter = logging.Formatter(
        '%(asctime)s, '
        '%(levelname)s, '
        '%(message)s, '
        '%(name)s'
    )

    stream_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)


class MissingTokensError(Exception):
    """Отсутствуют обязательные переменные окружения."""


class ApiAnswerError(Exception):
    """Исключение при некорректном ответе API."""


def check_tokens():
    """Проверяет доступность переменных окружения."""
    tokens = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'VK_TOKEN': VK_TOKEN,
        'VK_USER_ID': VK_USER_ID,
    }
    missing_tokens = []
    for token_name, token_value in tokens.items():
        if not token_value:
            logger.critical(f'Отсутствует переменная окружения {token_name}')
            missing_tokens.append(token_name)
    if missing_tokens:
        raise MissingTokensError(
            f'Отсутствуют переменные окружения: {", ".join(missing_tokens)}'
        )
    logger.info('Все переменные окружения на месте')


def send_message(vk, message):
    """Отправляет сообщение пользователю в VK."""
    logger.debug('Начинаем отправку сообщения: %s', message)
    try:
        vk.messages.send(
            user_id=VK_USER_ID,
            message=message,
            random_id=random.randint(0, 2**31 - 1),
        )
        logger.debug('Сообщение отправлено: %s', message)
        return True
    except (ApiError, requests.RequestException) as error:
        logger.exception('Ошибка при отправке сообщения: %s', error)
        return False


def get_api_answer(timestamp):
    """Делает запрос к API Практикума и возвращает ответ в виде словаря."""
    payload = {'from_date': timestamp}
    request_data = {
        'url': ENDPOINT,
        'headers': HEADERS,
        'params': payload,
    }

    logger.debug(
        'Начинаем запрос к API: адрес %(url)s,'
        'заголовки %(headers)s,'
        'параметры %(params)s',
        request_data,
    )

    try:
        response = requests.get(**request_data)
    except requests.exceptions.RequestException as error:
        raise ConnectionError(f'Не удалось подключиться к API: {error}')

    if response.status_code != http.HTTPStatus.OK:
        raise ApiAnswerError(
            f'API вернул некорректный статус-код: {response.status_code}. '
            f'Ответ: {response.text}'
        )

    try:
        return response.json()
    except ValueError:
        raise ApiAnswerError('Ответ API не удалось привести к формату JSON')


def check_response(response):
    """Проверяет ответ API и возвращает список домашних работ."""
    if not isinstance(response, dict):
        raise TypeError(
            f'Ответ API вместо словаря дает тип: {type(response).__name__}')

    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ "homeworks"')

    hmwrks = response['homeworks']
    if not isinstance(hmwrks, list):
        raise TypeError(
            f'Ключ "hmwrks" вместо списка дает тип: {type(hmwrks).__name__}')

    logger.debug(
        'Ответ API успешно проверен. Получено работ: %d',
        len(hmwrks)
    )
    return hmwrks


def parse_status(homework):
    """Извлекает статус работы и возвращает текст сообщения."""
    if not isinstance(homework, dict):
        raise TypeError(
            f'Ожидался словарь, получен тип {type(homework).__name__}')

    if 'homework_name' not in homework:
        raise KeyError('В ответе API нет ключа "homework_name"')

    if 'status' not in homework:
        raise KeyError('В ответе API нет ключа "status"')

    homework_name = homework['homework_name']
    status = homework['status']

    if status not in HOMEWORK_VERDICTS:
        raise ValueError(f'Неизвестный статус работы: {status}')

    verdict = HOMEWORK_VERDICTS[status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    check_tokens()

    # Создаем сессию для бота
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    timestamp = int(time.time())

    while True:
        try:
            # запрос к API
            response = get_api_answer(timestamp)
            # проверка ответа
            homeworks = check_response(response)
            # дополнительный флаг доставки всех вердиктов
            all_sent = True

            # если есть обновления, то получить статус и отправить сообщение
            if homeworks:
                for homework in homeworks:
                    message = parse_status(homework)
                    success = send_message(vk, message)
                    if not success:
                        all_sent = False
                        logger.error(
                            'Не удалось отправить вердикт по работе %s',
                            homework.get(
                                'homework_name',
                                'неизвестная работа')
                        )
            else:
                logger.debug('Новых статусов в ответе API нет.')

            if all_sent:
                timestamp = response.get('current_date', timestamp)

        except Exception as error:
            # логируем сбой
            message = f'Сбой в работе программы: {error}'
            logger.error(message, exc_info=True)
            try:
                send_message(vk, message)
            except Exception as send_error:
                logger.exception(
                    'Не удалось отправить уведомление об ошибке: %s',
                    send_error
                )
        finally:
            # подожать некоторое время и вернуться в начало цикла
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Произошла ошибка: {error}')
        sys.exit(1)
    else:
        sys.exit(0)
